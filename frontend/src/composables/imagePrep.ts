/**
 * 报告/检查单照片的本地预处理：压缩、摆正、重新编码。
 *
 * 三件事，全部在浏览器里完成：
 * 1. 长边压到 `IMAGE_MAX_EDGE`，避免手机原图（上万像素、十几 MB）直接上传；
 * 2. 用 canvas 重新编码，**顺带丢掉 EXIF**——手机照片通常带 GPS、拍摄设备与时间；
 * 3. 按拍摄方向摆正（`imageOrientation: 'from-image'`），否则竖着拍的报告 OCR 会读成横的。
 *
 * 这里**不判断图片内容**，也不做任何病情判别：是不是「报告/检查单」由用户在界面上点选；
 * 片子和身体照片按已确认边界**不上传**，只给固定的分流提示（`FILM_NOTICE`）。
 */

/** 长边上限（像素）。A4 报告照片压到 2400 像素约 170–200 dpi，够 OCR 认字，又不会传十几 MB。 */
export const IMAGE_MAX_EDGE = 2400
/** 压完仍超过 `IMAGE_TARGET_BYTES` 时依次降质重编；都不达标就接受最后一次，只要没超过后端上限。 */
export const IMAGE_QUALITY_STEPS = [0.85, 0.7, 0.55]
/** 压缩目标体积。压到它就停，OCR 认字够用且上传快。 */
export const IMAGE_TARGET_BYTES = 8 * 1024 * 1024
/** 与后端 `attachment_max_bytes` 一致（2026-09-21 为 30 MB）；真正判定仍以服务端为准。 */
export const IMAGE_MAX_BYTES = 30 * 1024 * 1024
const IMAGE_MAX_MB = IMAGE_MAX_BYTES / (1024 * 1024)
const IMAGE_MAX_LABEL = `${Number.isInteger(IMAGE_MAX_MB) ? IMAGE_MAX_MB : IMAGE_MAX_MB.toFixed(1)} MB`

/** 浏览器能可靠解码、且后端会收的图片类型。统一转成 JPEG 上传，所以后端只需认 JPEG。 */
export const IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
/** iPhone 默认存 HEIC/HEIF，浏览器解不开；要单独给说法，否则用户只看到「格式不支持」。 */
const UNDECODABLE_EXTENSIONS = ['heic', 'heif']

/** 用户点选「片子/身体照片」时显示的固定文案：不做判读，只分流。 */
export const FILM_NOTICE =
  '本产品不判读 X 光、CT、MRI 片子，也不评价身体照片。请携带原片到相应科室就诊；有明显不适或急症表现请及时就医。'

export type ImagePrepReason =
  | 'not_image'
  | 'undecodable'
  | 'too_large'
  | 'decode_failed'
  | 'output_failed'

export class ImagePrepError extends Error {
  readonly reason: ImagePrepReason

  constructor(reason: ImagePrepReason, message: string) {
    super(message)
    this.name = 'ImagePrepError'
    this.reason = reason
  }
}

function extensionOf(fileName: string): string {
  return fileName.split('.').pop()?.toLowerCase() || ''
}

export function isAcceptedImageType(file: File): boolean {
  return IMAGE_MIME_TYPES.includes(file.type) || IMAGE_EXTENSIONS.includes(extensionOf(file.name))
}

export function isUndecodableImage(file: File): boolean {
  return UNDECODABLE_EXTENSIONS.includes(extensionOf(file.name))
}

/** 等比缩到长边不超过 `maxEdge`；本来就够小就原样返回（**不放大**）。 */
export function scaledImageSize(
  width: number,
  height: number,
  maxEdge: number = IMAGE_MAX_EDGE,
): { width: number; height: number } {
  const longest = Math.max(width, height)
  if (!Number.isFinite(longest) || longest <= 0) return { width: 0, height: 0 }
  if (longest <= maxEdge) return { width: Math.round(width), height: Math.round(height) }
  const ratio = maxEdge / longest
  return {
    width: Math.max(1, Math.round(width * ratio)),
    height: Math.max(1, Math.round(height * ratio)),
  }
}

/** 与后端文件名规则（≤120 字符）留出余量，并统一改成 `.jpg`。 */
const MAX_NAME_LENGTH = 100

export function preparedImageName(originalName: string, extension = 'jpg'): string {
  const base = originalName.replace(/\.[^.]+$/, '').trim() || '检查报告'
  return `${base.slice(0, MAX_NAME_LENGTH)}.${extension}`
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      blob => {
        if (blob) resolve(blob)
        else reject(new ImagePrepError('output_failed', '图片转换失败，请换一张或改用 PDF 上传'))
      },
      type,
      quality,
    )
  })
}

/**
 * 把用户选的图片处理成可直接上传的文件。失败一律抛 `ImagePrepError`，
 * 消息是给用户看的中文短句（调用方直接透传即可）。
 */
export async function prepareImageForUpload(file: File): Promise<File> {
  if (isUndecodableImage(file)) {
    throw new ImagePrepError(
      'undecodable',
      'iPhone 的 HEIC 照片浏览器打不开，请先在相册里导出为 JPG 再上传',
    )
  }
  if (!isAcceptedImageType(file)) {
    throw new ImagePrepError('not_image', '图片只支持 JPG、PNG、WebP；报告也可以直接传 PDF')
  }
  if (file.size > IMAGE_MAX_BYTES) {
    // 文案从常量派生，避免上限调整后提示还写着旧数字。
    throw new ImagePrepError('too_large', `单张图片不能超过 ${IMAGE_MAX_LABEL}`)
  }

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    throw new ImagePrepError('decode_failed', '这张图片解不开，可能已损坏，请换一张或改用 PDF 上传')
  }

  try {
    const { width, height } = scaledImageSize(bitmap.width, bitmap.height)
    if (!width || !height) {
      throw new ImagePrepError('decode_failed', '图片尺寸异常，请换一张或改用 PDF 上传')
    }
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) {
      throw new ImagePrepError('output_failed', '当前浏览器无法处理图片，请改用 PDF 上传')
    }
    context.drawImage(bitmap, 0, 0, width, height)

    let latest: Blob | null = null
    for (const quality of IMAGE_QUALITY_STEPS) {
      latest = await canvasToBlob(canvas, 'image/jpeg', quality)
      if (latest.size <= IMAGE_TARGET_BYTES) break
    }
    if (!latest) {
      throw new ImagePrepError('output_failed', '图片转换失败，请换一张或改用 PDF 上传')
    }
    return new File([latest], preparedImageName(file.name), {
      type: 'image/jpeg',
      lastModified: Date.now(),
    })
  } finally {
    bitmap.close()
  }
}