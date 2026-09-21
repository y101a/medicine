import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  FILM_NOTICE,
  IMAGE_MAX_BYTES,
  IMAGE_QUALITY_STEPS,
  IMAGE_TARGET_BYTES,
  ImagePrepError,
  isAcceptedImageType,
  isUndecodableImage,
  prepareImageForUpload,
  preparedImageName,
  scaledImageSize,
} from './imagePrep'

/**
 * jsdom 既没有 canvas 也没有 createImageBitmap，两者都必须打桩，否则测的不是真实路径。
 * 体积用 `Object.defineProperty` 伪造：真去分配 8 MB 只会拖慢测试，判定逻辑仍是同一个 `blob.size`。
 */
const drawImage = vi.fn()
let blobSizes: number[] = []
let toBlobArgs: { type: string; quality: number }[] = []
let contextAvailable = true

function imageFile(name = '报告.jpg', type = 'image/jpeg', byteSize = 3 * 1024 * 1024): File {
  const file = new File(['x'], name, { type })
  Object.defineProperty(file, 'size', { value: byteSize })
  return file
}

function stubBitmap(width = 6000, height = 4000) {
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width, height, close: vi.fn() })))
}

beforeEach(() => {
  drawImage.mockClear()
  blobSizes = []
  toBlobArgs = []
  contextAvailable = true
  stubBitmap()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    (() =>
      contextAvailable ? ({ drawImage } as unknown as CanvasRenderingContext2D) : null) as typeof HTMLCanvasElement.prototype.getContext,
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (
    this: HTMLCanvasElement,
    callback: BlobCallback,
    type?: string,
    quality?: number,
  ) {
    toBlobArgs.push({ type: type ?? '', quality: quality ?? 0 })
    const blob = new Blob(['x'], { type: type ?? 'image/jpeg' })
    Object.defineProperty(blob, 'size', { value: blobSizes.shift() ?? 1024 * 1024 })
    callback(blob)
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('图片本地预处理', () => {
  it('长边超过上限时等比缩小，够小则原样返回且不放大', () => {
    expect(scaledImageSize(6000, 4000)).toEqual({ width: 2400, height: 1600 })
    expect(scaledImageSize(4000, 6000)).toEqual({ width: 1600, height: 2400 })
    expect(scaledImageSize(1200, 900)).toEqual({ width: 1200, height: 900 })
    expect(scaledImageSize(0, 0)).toEqual({ width: 0, height: 0 })
  })

  it('只认 JPG/PNG/WebP，并单独识别 HEIC', () => {
    expect(isAcceptedImageType(imageFile('a.jpg', 'image/jpeg'))).toBe(true)
    expect(isAcceptedImageType(imageFile('a.png', 'image/png'))).toBe(true)
    expect(isAcceptedImageType(imageFile('a.webp', 'image/webp'))).toBe(true)
    expect(isAcceptedImageType(imageFile('a.pdf', 'application/pdf'))).toBe(false)
    expect(isAcceptedImageType(imageFile('a.svg', 'image/svg+xml'))).toBe(false)
    expect(isUndecodableImage(imageFile('IMG_1.HEIC', 'image/heic'))).toBe(true)
    expect(isUndecodableImage(imageFile('a.jpg', 'image/jpeg'))).toBe(false)
  })

  it('文件名统一换成 .jpg 并压到长度上限内', () => {
    expect(preparedImageName('IMG_1234.HEIC')).toBe('IMG_1234.jpg')
    expect(preparedImageName('检查报告.png')).toBe('检查报告.jpg')
    expect(preparedImageName('')).toBe('检查报告.jpg')
    expect(preparedImageName(`${'长'.repeat(300)}.jpg`)).toHaveLength(104)
  })

  it('成功路径：按缩放后尺寸绘制，输出 JPEG，文件名换成 .jpg', async () => {
    const prepared = await prepareImageForUpload(imageFile('IMG_1234.png', 'image/png'))
    expect(drawImage).toHaveBeenCalledTimes(1)
    expect(drawImage.mock.calls[0].slice(1)).toEqual([0, 0, 2400, 1600])
    expect(toBlobArgs[0]).toEqual({ type: 'image/jpeg', quality: IMAGE_QUALITY_STEPS[0] })
    expect(prepared.name).toBe('IMG_1234.jpg')
    expect(prepared.type).toBe('image/jpeg')
  })

  it('本来就不大的图片不放大，只重新编码一遍', async () => {
    stubBitmap(800, 600)
    await prepareImageForUpload(imageFile())
    expect(drawImage.mock.calls[0].slice(1)).toEqual([0, 0, 800, 600])
  })

  it('HEIC 直接给出可操作的提示，不去尝试解码', async () => {
    const bitmap = vi.fn()
    vi.stubGlobal('createImageBitmap', bitmap)
    await expect(
      prepareImageForUpload(imageFile('IMG_1.HEIC', 'image/heic')),
    ).rejects.toMatchObject({ reason: 'undecodable' })
    expect(bitmap).not.toHaveBeenCalled()
  })

  it('非图片类型与超限体积都在解码前拦下', async () => {
    await expect(prepareImageForUpload(imageFile('a.svg', 'image/svg+xml'))).rejects.toMatchObject({
      reason: 'not_image',
    })
    const oversized = imageFile('大图.jpg', 'image/jpeg', IMAGE_MAX_BYTES + 1)
    await expect(prepareImageForUpload(oversized)).rejects.toMatchObject({ reason: 'too_large' })
    await expect(prepareImageForUpload(oversized)).rejects.toThrow('单张图片不能超过 30 MB')
  })

  it('解码失败与拿不到 2D 上下文时给出不同提示', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => {
        throw new Error('boom')
      }),
    )
    await expect(prepareImageForUpload(imageFile())).rejects.toMatchObject({ reason: 'decode_failed' })

    stubBitmap(800, 600)
    contextAvailable = false
    await expect(prepareImageForUpload(imageFile())).rejects.toMatchObject({ reason: 'output_failed' })
  })

  it('压不到目标体积时依次降质重编，达标即停', async () => {
    blobSizes = [IMAGE_TARGET_BYTES + 1, 1024]
    await prepareImageForUpload(imageFile())
    expect(toBlobArgs.map(item => item.quality)).toEqual([
      IMAGE_QUALITY_STEPS[0],
      IMAGE_QUALITY_STEPS[1],
    ])
    expect(toBlobArgs.every(item => item.type === 'image/jpeg')).toBe(true)
  })

  it('降质到底仍超标时接受最后一次结果，不报错', async () => {
    blobSizes = [IMAGE_TARGET_BYTES + 1, IMAGE_TARGET_BYTES + 1, IMAGE_TARGET_BYTES + 1]
    const prepared = await prepareImageForUpload(imageFile())
    expect(prepared.type).toBe('image/jpeg')
    expect(toBlobArgs).toHaveLength(IMAGE_QUALITY_STEPS.length)
  })

  it('片子/身体照片的固定提示只做分流，不含判读表述', () => {
    expect(FILM_NOTICE).toContain('不判读')
    expect(FILM_NOTICE).toContain('就诊')
    expect(new ImagePrepError('not_image', 'x')).toMatchObject({
      name: 'ImagePrepError',
      reason: 'not_image',
    })
  })
})