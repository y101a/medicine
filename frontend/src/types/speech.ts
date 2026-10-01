/**
 * 语音输出（TTS）的前端契约类型（方案 `VOICE_OUTPUT_PLAN.md` §3、§4、§6.1）。
 *
 * 三条边界写在这里，别在别处再定义一份：
 * 1. 前端只认识**产品枚举** `speechPreset`，不认识供应商的 `voice`/`instruction`，
 *    更不允许传任意模型或自由文本指令（映射全在服务端常量里）。
 * 2. 朗读文本由服务端按 `messageId` 从数据库重新取；前端传的文本**只用于本地长度预检**。
 * 3. 音频是一次性临时结果：只有内存里的 Blob 与 Object URL，不进 localStorage。
 */

/** 服务端默认预设，也是预设列表不可用时的兜底（与契约 `default` 取值一致）。 */
export const DEFAULT_SPEECH_PRESET = 'mandarin_female'

/** 只允许这三档语速（契约 §4.2 冻结）。 */
export const SPEECH_RATES = [0.8, 1.0, 1.2] as const

export type SpeechRate = (typeof SPEECH_RATES)[number]

export const DEFAULT_SPEECH_RATE: SpeechRate = 1.0

/** 语速选项的展示文案；取值必须与 `SPEECH_RATES` 一致（前端不提供第四档）。 */
export const SPEECH_RATE_OPTIONS: { value: SpeechRate; label: string }[] = [
  { value: 0.8, label: '慢速' },
  { value: 1.0, label: '标准语速' },
  { value: 1.2, label: '快速' },
]

/**
 * 服务端清洗后的朗读文本上限（Unicode 字符，契约 §4.2）。
 * 前端只用它做**发送前预检**：明显超长的回答直接提示分段朗读，不白跑一次生成请求。
 * 真正的上限判定仍在服务端（`SPEECH_TEXT_TOO_LONG`），这里不是替代品。
 */
export const SPEECH_MAX_TEXT_CHARS = 4000

export interface SpeechPreset {
  /** 产品枚举，如 `mandarin_female`、`cantonese`；服务端白名单，前端不猜。 */
  id: string
  label: string
  language: string
  /** 方言标识；普通话为 `null`。 */
  dialect: string | null
}

/** `GET /speech/presets` 的响应：只含产品字段，不含模型、供应商地址或 instruction。 */
export interface SpeechPresetList {
  default: string
  items: SpeechPreset[]
}

/**
 * 服务端预设列表拉不到时的最小兜底：只保留默认普通话。
 *
 * 故意**不**在这里列方言——方言与音色的映射由后端白名单维护，前端自己列一份迟早漂移；
 * 列表不可用时宁可少给选项，也不给一个可能不被支持的方言。
 */
export const FALLBACK_SPEECH_PRESETS: SpeechPresetList = {
  default: DEFAULT_SPEECH_PRESET,
  items: [
    { id: DEFAULT_SPEECH_PRESET, label: '普通话·自然女声', language: 'zh-CN', dialect: null },
  ],
}

/**
 * 单播放器状态机（契约 §6.1）：`idle -> loading -> playing <-> paused -> idle`，任何阶段可进 `error`。
 *
 * 另加一个 `ready`：**音频已经拿到、但浏览器不允许自动播放**（没有有效用户手势）。
 * 契约 §6.2 要求这种情况降级为「语音已生成，点击播放」，没有它就无处安放这个中间态；
 * `ready` 与 `paused` 的区别是前者还没开始播过，用户点一下就是从头播。
 */
export type SpeechPlaybackState = 'idle' | 'loading' | 'ready' | 'playing' | 'paused'

/**
 * 服务端对用户消息的确定性语音输出意图（契约 §4.3）。
 *
 * `requested` 为 true 时不代表这条消息本身要变成音频，而是**这一轮回答完成后自动朗读**；
 * 判定规则全在服务端（`speech_intent.py`），前端不另写一套会漂移的正则。
 */
export interface SpeechOutputIntent {
  requested: boolean
  /** 用户明确说出的方言对应的预设；没识别出来时为 null（用用户当前选择的预设）。 */
  speechPreset: string | null
}