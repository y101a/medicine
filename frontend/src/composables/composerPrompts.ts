/**
 * 草稿为空且有附件时，界面自动补的默认提问。
 *
 * 放在独立模块而不是视图里，是因为同一份文本有两个消费方：
 * 1. `HomeView.send()` 要把它**原样提交给后端**——模型必须看到这句话；
 * 2. `isHiddenAutoPrompt()` 要按**整句相等**判断「这句不该显示给用户」（用户 2026-09-22 要求）。
 *
 * 写在一处，改文案时隐藏逻辑、单测与 e2e 会自动跟随，不会出现「改了文案、隐藏却失效」。
 */

/** 只传文档时的默认提问。 */
export const DEFAULT_ATTACHMENT_PROMPT =
  '请帮我解读上传的病历文档，解释其中的医学术语和指标，并在必要时给出就医分流建议；不要作出确诊。'

/**
 * 只传图片时的默认提问：仍然只要「整理可见信息 + 下一步看什么科」，不要疾病判断。
 * 2026-09-23 起补上「说明书上的文字」——说明书成为独立类别（`medication_leaflet`）后，
 * 这句默认提问也要覆盖它；但用药建议与剂量换算的边界由卡片上的类别边界文案与
 * 服务端上下文指令共同保证，不靠这句话。
 */
export const IMAGE_ATTACHMENT_PROMPT =
  '请根据我上传的图片，帮我整理能读到的信息（报告上的指标、说明书上的文字，或片子和照片上肉眼可见、非诊断性的情况），并说明下一步该看什么科；不要作出确诊，也不要判读影像。'

/**
 * 这两句照旧发给后端，但**不在对话里显示**：用户只是没打字，
 * 不该看到这句机器话被当成自己说的话；用户自己打的字照常显示。
 *
 * 注意：会话标题仍由后端取首条消息前 40 字（`backend/app/services/consultations.py:276-277`），
 * 所以图片/文档作为第一条消息时，标题还会是这句话的前半句——改标题要后端配合。
 */
export const HIDDEN_AUTO_PROMPTS = new Set([DEFAULT_ATTACHMENT_PROMPT, IMAGE_ATTACHMENT_PROMPT])

/** 判断某条消息是不是「自动补的默认提问」（按整句相等，不按来源标记）。 */
export function isHiddenAutoPrompt(content: string): boolean {
  return HIDDEN_AUTO_PROMPTS.has(content.trim())
}