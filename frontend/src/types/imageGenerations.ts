/**
 * AI 科普配图（图片生成）的前端契约类型。
 *
 * 来源：`IMAGE_GENERATION_PLAN.md` 第 4 节（冻结 API 契约）与第 7.1 节（前端文件清单）。
 * 全部字段都是**服务端返回的事实**，前端不自行推断任务状态、不拼供应商 URL、不接触 API Key。
 */

/** 契约固定三种风格；前端不能自定义，也不能改模型。 */
export type ImageGenerationStyle =
  | 'medical_illustration'
  | 'flat_illustration'
  | 'friendly_cartoon'

/** 契约固定四种比例；1K 像素映射（如 `1:1=1280*1280`）由服务端决定，前端不传像素。 */
export type ImageGenerationAspectRatio = '1:1' | '4:3' | '3:4' | '16:9'

/**
 * 任务状态机（契约 §4.2）。
 * `submitted`/`running` 是「还在生成」，需要轮询；其余都是终态。
 */
export type ImageGenerationStatus =
  | 'submitted'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'expired'

/** 创建任务的请求体（契约 §4.1）。`n`、分辨率、水印、模型都不在前端可控范围内。 */
export interface ImageGenerationRequest {
  /** 幂等键：同一用户重复提交必须返回同一任务，绝不能重复调用收费接口。 */
  clientRequestId: string
  /**
   * 来源消息。2026-09-25 起允许是**命中意图的用户消息**：服务端会重新解密它的原文作为主题
   * （`backend/app/services/image_generations.py:226`），所以下面的 `prompt` 只是契约要求的
   * 非空占位，不会被外发；前端也不再让用户单独编辑提示词。
   */
  sourceMessageId: string
  prompt: string
  /** 省略则由服务端套用固定默认值（`medical_illustration` / `4:3`），前端不提供选择。 */
  style?: ImageGenerationStyle
  aspectRatio?: ImageGenerationAspectRatio
  noticeAccepted: true
  noticeVersion: string
}

/** 任务（契约 §4.1 响应 / §4.2 查询）。 */
export interface ImageGeneration {
  id: string
  sourceMessageId: string
  status: ImageGenerationStatus
  style: ImageGenerationStyle
  aspectRatio: ImageGenerationAspectRatio
  /** 服务端固定模型（方案为 `wan2.6-t2i`），只用于展示，前端不能改。 */
  model: string
  /** 成品是否可读；为 false 时不要请求内容接口（会拿到 409）。 */
  imageAvailable: boolean
  imageExpiresAt: string | null
  createdAt: string
  updatedAt: string
}

/** 提示词上限（契约 §2.3：最多 500 字，由服务端最终校验）。 */
export const IMAGE_GENERATION_PROMPT_MAX_LENGTH = 500

export const IMAGE_GENERATION_STYLE_LABELS: Record<ImageGenerationStyle, string> = {
  medical_illustration: '医学科普插画',
  flat_illustration: '简洁扁平插画',
  friendly_cartoon: '友好卡通示意',
}

export const IMAGE_GENERATION_ASPECT_RATIO_LABELS: Record<ImageGenerationAspectRatio, string> = {
  '1:1': '正方形 1:1',
  '4:3': '横向 4:3',
  '3:4': '竖向 3:4',
  '16:9': '宽屏 16:9',
}

export const IMAGE_GENERATION_STATUS_LABELS: Record<ImageGenerationStatus, string> = {
  submitted: '等待生成',
  running: '正在生成',
  completed: '已生成',
  failed: '生成失败',
  cancelled: '已取消',
  expired: '已过期',
}

/** 还在生成、需要继续轮询的状态。 */
export const IMAGE_GENERATION_ACTIVE_STATUSES: ImageGenerationStatus[] = ['submitted', 'running']

/**
 * 生成图的用途声明。**必须显示在成品卡片上**：图片由 AI 生成，只作科普示意。
 * 用户 2026-09-24 选择了「走《人工智能生成合成内容标识办法》第九条：图内无标识」，
 * 所以标识责任落在**界面提示 + 用户协议 + 服务端元数据隐式标识**上，界面这一层不能省。
 */
export const IMAGE_GENERATION_DISCLAIMER =
  'AI 生成·科普示意，不作为诊断依据；也不作为检查或治疗依据——图中结构或文字可能有误，请以医生意见为准。'