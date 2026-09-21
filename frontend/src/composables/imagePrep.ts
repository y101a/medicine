/**
 * 医学图片的本地预处理：压缩、摆正、重新编码。
 *
 * 契约见 `backend/docs/MEDICAL_IMAGES.md`（2026-09-21 冻结）。本地这层只改善体验，
 * **后端才是权威**：它会重新解码、嗅探真实类型、移除元数据并统一转成 WebP，
 * 所以这里不做任何「相信前端」的判断，也不判断图片内容与病情。
 *
 * 三件事，全部在浏览器里完成：
 * 1. 长边压到 `IMAGE_MAX_EDGE`，并在必要时继续降长边，直到压进 `IMAGE_MAX_BYTES`；
 * 2. 用 canvas 重新编码，**顺带丢掉 EXIF**——手机照片通常带 GPS、拍摄设备与时间；
 * 3. 按拍摄方向摆正（`imageOrientation: 'from-image'`），否则竖着拍的报告 OCR 会读成横的。
 */

/** 长边上限（像素），与后端规范化目标一致。A4 报告照片约 170–200 dpi，够识别文字。 */
export const IMAGE_MAX_EDGE = 2400
/** 压缩目标 = 上传上限：与后端 `image_max_bytes`（5 MiB）一致，超过必然被服务端拒绝。 */
export const IMAGE_MAX_BYTES = 5 * 1024 * 1024
const IMAGE_MAX_MB = IMAGE_MAX_BYTES / (1024 * 1024)
/** 文案从常量派生，避免上限调整后提示还写着旧数字。 */
const IMAGE_MAX_LABEL = `${Number.isInteger(IMAGE_MAX_MB) ? IMAGE_MAX_MB : IMAGE_MAX_MB.toFixed(1)} MiB`
/** 本地拒绝的输入上限，只为保护浏览器内存；超过它的原图先让用户自己裁剪。 */
export const IMAGE_INPUT_MAX_BYTES = 40 * 1024 * 1024
/** 压不进上限时依次降质重编；仍不达标就再降一档长边重来。 */
export const IMAGE_QUALITY_STEPS = [0.85, 0.7, 0.55, 0.45]
/** 降长边的最大轮数（配合上面的质量序列，实测足以把手机原图压进 5 MiB）。 */
export const IMAGE_MAX_ROUNDS = 3
/** 后端要求：宽高均至少 32 px、宽高比不超过 20:1——本地先拦，能给出更具体的提示。 */
export const IMAGE_MIN_EDGE = 32
export const IMAGE_MAX_ASPECT_RATIO = 20

/** 浏览器能可靠解码、且后端会收的类型（后端再统一转 WebP）。 */
export const IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
/** iPhone 默认存 HEIC/HEIF，浏览器解不开；要单独给说法，否则用户只看到「格式不支持」。 */
const UNDECODABLE_EXTENSIONS = ['heic', 'heif']

export type ImageCategory = 'report' | 'medical_imaging' | 'body_photo'

/** 类别选择器上的名字。 */
export const IMAGE_CATEGORY_LABELS: Record<ImageCategory, string> = {
  report: '报告 / 检查单',
  medical_imaging: 'X 光 / CT / MRI 片子',
  body_photo: '患处或身体照片',
}

/**
 * 三类图片各不相同的能力边界文案（契约要求分别显示）。
 * 都只描述「会做什么、不会做什么」，不给任何疾病判断。
 */
export const IMAGE_CATEGORY_NOTICES: Record<ImageCategory, string> = {
  report: '会读取照片上的文字并整理成要点；识别可能出错，请以纸质报告为准。',
  medical_imaging:
    '只识别影像类型、部位与片子上可见的文字，不判断病灶、阴影、骨折等情况；请携带正式影像报告咨询医生。',
  body_photo:
    '只整理肉眼可见、非诊断性的事实（如颜色、范围、是否有明显出血），不判断是什么病；急症请立即就医或拨 120。',
}

/** 首次上传图片的一次性说明：敏感信息 + 第三方外发 + 保留期限（契约第 7 节）。 */
export const IMAGE_CONSENT_NOTICE =
  '照片属于医疗健康敏感信息：会先在本地压缩、去掉拍摄位置等元数据，再发送给服务端固定的阿里云视觉模型识别；' +
  '画面上的姓名、住院号、条码无法自动去除，建议先遮挡。规范化图片加密保存 90 天，识别文字随会话保留，' +
  '可随时删除附件、会话或账号。请勿上传他人资料。'

export type ImagePrepReason =
  | 'not_image'
  | 'undecodable'
  | 'too_large'
  | 'too_small'
  | 'bad_ratio'
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

/** 与后端文件名规则（≤120 字符）留出余量，并统一改成 `.jpg`（后端会再转 WebP）。 */
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
 * 把用户选的图片处理成可直接上传的文件（保证 ≤ `IMAGE_MAX_BYTES`）。
 * 失败一律抛 `ImagePrepError`，消息是给用户看的中文短句，调用方直接透传。
 */
export async function prepareImageForUpload(file: File): Promise<File> {
  if (isUndecodableImage(file)) {
    throw new ImagePrepError(
      'undecodable',
      'iPhone 的 HEIC 照片浏览器打不开，请先在相册里导出为 JPG 再上传',
    )
  }
  if (!isAcceptedImageType(file)) {
    throw new ImagePrepError(
      'not_image',
      '图片只支持 JPG、PNG、WebP；动图与截图外的其它格式请转成 JPG，报告也可以直接传 PDF',
    )
  }
  if (file.size > IMAGE_INPUT_MAX_BYTES) {
    throw new ImagePrepError('too_large', '图片太大，请先在相册里裁剪后再上传')
  }

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    throw new ImagePrepError('decode_failed', '这张图片解不开，可能已损坏，请换一张或改用 PDF 上传')
  }

  try {
    const shortest = Math.min(bitmap.width, bitmap.height)
    const longest = Math.max(bitmap.width, bitmap.height)
    if (!shortest || !longest) {
      throw new ImagePrepError('decode_failed', '图片尺寸异常，请换一张或改用 PDF 上传')
    }
    if (shortest < IMAGE_MIN_EDGE) {
      throw new ImagePrepError('too_small', '图片太小（最短边不足 32 像素），请重新拍摄或改用 PDF')
    }
    if (longest / shortest > IMAGE_MAX_ASPECT_RATIO) {
      throw new ImagePrepError('bad_ratio', '图片长宽比异常（超过 20:1），请裁剪后重试')
    }

    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d')
    if (!context) {
      throw new ImagePrepError('output_failed', '当前浏览器无法处理图片，请改用 PDF 上传')
    }

    let edge = IMAGE_MAX_EDGE
    for (let round = 0; round < IMAGE_MAX_ROUNDS; round += 1) {
      const { width, height } = scaledImageSize(bitmap.width, bitmap.height, edge)
      if (!width || !height) {
        throw new ImagePrepError('decode_failed', '图片尺寸异常，请换一张或改用 PDF 上传')
      }
      canvas.width = width
      canvas.height = height
      context.drawImage(bitmap, 0, 0, width, height)

      for (const quality of IMAGE_QUALITY_STEPS) {
        const blob = await canvasToBlob(canvas, 'image/jpeg', quality)
        if (blob.size <= IMAGE_MAX_BYTES) {
          return new File([blob], preparedImageName(file.name), {
            type: 'image/jpeg',
            lastModified: Date.now(),
          })
        }
      }
      // 降到最低质量仍超上限：缩小长边再重来一轮。
      edge = Math.round(edge * 0.75)
    }
    throw new ImagePrepError(
      'too_large',
      `压缩后仍超过 ${IMAGE_MAX_LABEL}，请裁剪图片后重试或改用 PDF 上传`,
    )
  } finally {
    bitmap.close()
  }
}