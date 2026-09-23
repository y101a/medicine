import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  IMAGE_CATEGORY_LABELS,
  IMAGE_CATEGORY_NOTICES,
  IMAGE_CONSENT_NOTICE,
  IMAGE_INPUT_MAX_BYTES,
  IMAGE_MAX_BYTES,
  IMAGE_MAX_ROUNDS,
  IMAGE_QUALITY_STEPS,
  ImagePrepError,
  isAcceptedImageType,
  isUndecodableImage,
  prepareImageForUpload,
  preparedImageName,
  scaledImageSize,
} from './imagePrep'

/**
 * jsdom 既没有 canvas 也没有 createImageBitmap，两者都必须打桩，否则测的不是真实路径。
 * 体积用 `Object.defineProperty` 伪造：真去分配 5 MiB 只会拖慢测试，判定用的仍是同一个 `blob.size`。
 */
const drawImage = vi.fn()
const close = vi.fn()
let blobSizes: number[] = []
let toBlobArgs: { type: string; quality: number }[] = []
let contextAvailable = true

function imageFile(name = '报告.jpg', type = 'image/jpeg', byteSize = 3 * 1024 * 1024): File {
  const file = new File(['x'], name, { type })
  Object.defineProperty(file, 'size', { value: byteSize })
  return file
}

function stubBitmap(width = 6000, height = 4000) {
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width, height, close })))
}

beforeEach(() => {
  drawImage.mockClear()
  close.mockClear()
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
    expect(isAcceptedImageType(imageFile('a.gif', 'image/gif'))).toBe(false)
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

  it('成功路径：按缩放后尺寸绘制，输出 JPEG，文件名换成 .jpg，并释放 bitmap', async () => {
    const prepared = await prepareImageForUpload(imageFile('IMG_1234.png', 'image/png'))
    expect(drawImage).toHaveBeenCalledTimes(1)
    expect(drawImage.mock.calls[0].slice(1)).toEqual([0, 0, 2400, 1600])
    expect(toBlobArgs[0]).toEqual({ type: 'image/jpeg', quality: IMAGE_QUALITY_STEPS[0] })
    expect(prepared.name).toBe('IMG_1234.jpg')
    expect(prepared.type).toBe('image/jpeg')
    expect(close).toHaveBeenCalled()
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

  it('非图片类型与过大的原图都在解码前拦下', async () => {
    await expect(prepareImageForUpload(imageFile('a.svg', 'image/svg+xml'))).rejects.toMatchObject({
      reason: 'not_image',
    })
    const huge = imageFile('大图.jpg', 'image/jpeg', IMAGE_INPUT_MAX_BYTES + 1)
    await expect(prepareImageForUpload(huge)).rejects.toMatchObject({ reason: 'too_large' })
    await expect(prepareImageForUpload(huge)).rejects.toThrow('请先在相册里裁剪')
  })

  it('过小与长宽比异常的图片给出各自的提示', async () => {
    stubBitmap(20, 20)
    await expect(prepareImageForUpload(imageFile())).rejects.toMatchObject({ reason: 'too_small' })

    stubBitmap(4000, 100)
    await expect(prepareImageForUpload(imageFile())).rejects.toMatchObject({ reason: 'bad_ratio' })
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

  it('超过上传上限时依次降质重编，达标即停', async () => {
    blobSizes = [IMAGE_MAX_BYTES + 1, 1024]
    await prepareImageForUpload(imageFile())
    expect(toBlobArgs.map(item => item.quality)).toEqual([
      IMAGE_QUALITY_STEPS[0],
      IMAGE_QUALITY_STEPS[1],
    ])
    expect(drawImage).toHaveBeenCalledTimes(1)
  })

  it('降到最低质量仍超标时缩小长边重来一轮', async () => {
    blobSizes = [
      IMAGE_MAX_BYTES + 1,
      IMAGE_MAX_BYTES + 1,
      IMAGE_MAX_BYTES + 1,
      IMAGE_MAX_BYTES + 1,
      1024,
    ]
    await prepareImageForUpload(imageFile())
    expect(drawImage).toHaveBeenCalledTimes(2)
    // 第一轮 2400×1600，第二轮长边乘 0.75 → 1800×1200
    expect(drawImage.mock.calls[1].slice(1)).toEqual([0, 0, 1800, 1200])
    expect(toBlobArgs.filter(item => item.quality === IMAGE_QUALITY_STEPS[0])).toHaveLength(2)
  })

  it('所有轮次都压不进上限时报错，而不是上传一个超大文件', async () => {
    blobSizes = Array.from(
      { length: IMAGE_MAX_ROUNDS * IMAGE_QUALITY_STEPS.length },
      () => IMAGE_MAX_BYTES + 1,
    )
    const error = await prepareImageForUpload(imageFile()).catch(cause => cause)
    expect(error).toMatchObject({ reason: 'too_large' })
    expect(String(error.message)).toContain('压缩后仍超过 5 MiB')
  })

  it('五类各自的能力边界文案都不含判读表述，且首次说明含保留期限与外发声明', () => {
    expect(Object.keys(IMAGE_CATEGORY_NOTICES))
      .toEqual(['report', 'medical_imaging', 'body_photo', 'unrelated', 'medication_leaflet'])
    expect(IMAGE_CATEGORY_NOTICES.medical_imaging).toContain('不判断病灶')
    expect(IMAGE_CATEGORY_NOTICES.body_photo).toContain('不判断是什么病')
    expect(IMAGE_CATEGORY_NOTICES.report).toContain('以纸质报告为准')
    // 第四类：普通图片是成功附件，边界是「只做医疗相关检查、不作普通场景详细识别」。
    expect(IMAGE_CATEGORY_LABELS.unrelated).toBe('普通图片')
    expect(IMAGE_CATEGORY_NOTICES.unrelated).toContain('未检测到医疗健康相关内容')
    expect(IMAGE_CATEGORY_NOTICES.unrelated).toContain('不对普通场景作详细识别')
    // 第五类：药品说明书。用户 2026-09-23 拍板 D2=B2（新增类别）、D1=A3（用法用量原文照旧转录 + 强制限定语）。
    expect(IMAGE_CATEGORY_LABELS.medication_leaflet).toBe('药品说明书')
    expect(IMAGE_CATEGORY_NOTICES.medication_leaflet).toContain('含用法用量原文')
    expect(IMAGE_CATEGORY_NOTICES.medication_leaflet).toContain('不作用药建议')
    expect(IMAGE_CATEGORY_NOTICES.medication_leaflet).toContain('不换算剂量')
    expect(IMAGE_CATEGORY_NOTICES.medication_leaflet).toContain('遵医嘱或咨询药师')
    expect(IMAGE_CONSENT_NOTICE).toContain('90 天')
    expect(IMAGE_CONSENT_NOTICE).toContain('阿里云视觉模型')
    expect(IMAGE_CONSENT_NOTICE).toContain('建议先遮挡')
    expect(new ImagePrepError('not_image', 'x')).toMatchObject({
      name: 'ImagePrepError',
      reason: 'not_image',
    })
  })
})