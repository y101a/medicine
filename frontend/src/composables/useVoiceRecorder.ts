import { getCurrentInstance, onBeforeUnmount, ref } from 'vue'

export type VoiceRecorderState = 'idle' | 'requesting' | 'recording' | 'transcribing'

/** 与后端契约一致：单段录音上限 60 秒（百炼实时文档亦建议单次音频累加不超过 60s）。 */
export const VOICE_MAX_SECONDS = 60

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
]

/** 把浏览器的录音相关异常翻译成用户能看懂的中文，不暴露原始 message。 */
export function mediaErrorMessage(cause: unknown): string {
  const name = (cause as { name?: string } | null)?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '麦克风权限被拒绝，请在浏览器地址栏允许后重试'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return '没有检测到可用的麦克风'
  }
  if (name === 'NotReadableError') {
    return '麦克风被其他程序占用，请关闭后重试'
  }
  if (name === 'AbortError') {
    return '录音启动被中断，请重试'
  }
  return '无法开始录音，请检查麦克风后重试'
}

/**
 * 录音状态机：只产出「一段音频」，不做转写、不接触接口。
 *
 * 音频始终留在内存里，`stop()` 交给调用方上传；`cancel()` 直接丢弃。
 * 浏览器 API 全部做存在性判断，便于单测替换 `MediaRecorder`/`getUserMedia`。
 */
export function useVoiceRecorder(maxSeconds: number = VOICE_MAX_SECONDS) {
  // 能力检测放在调用时一次性完成：不支持就禁用按钮，并提示改走输入法语音。
  const supported = typeof MediaRecorder !== 'undefined'
    && Boolean(navigator.mediaDevices?.getUserMedia)
  const state = ref<VoiceRecorderState>('idle')
  const seconds = ref(0)
  const error = ref('')

  let stream: MediaStream | undefined
  let recorder: MediaRecorder | undefined
  let chunks: Blob[] = []
  let ticker: ReturnType<typeof setInterval> | undefined
  let settle: Promise<Blob | null> | undefined
  let discarding = false

  function release() {
    if (ticker !== undefined) {
      clearInterval(ticker)
      ticker = undefined
    }
    stream?.getTracks().forEach(track => track.stop())
    stream = undefined
    recorder = undefined
  }

  function pickMimeType(): string | undefined {
    if (typeof MediaRecorder.isTypeSupported !== 'function') return undefined
    return MIME_CANDIDATES.find(type => MediaRecorder.isTypeSupported(type))
  }

  function reset() {
    state.value = 'idle'
    seconds.value = 0
    error.value = ''
  }

  async function start(): Promise<boolean> {
    if (state.value !== 'idle') return false
    error.value = ''
    if (!supported) {
      error.value = '当前浏览器不支持录音，请改用输入法语音输入'
      return false
    }
    state.value = 'requesting'
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (cause) {
      state.value = 'idle'
      error.value = mediaErrorMessage(cause)
      return false
    }
    const mimeType = pickMimeType()
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    } catch {
      release()
      error.value = '当前浏览器不支持录音，请改用输入法语音输入'
      return false
    }

    chunks = []
    discarding = false
    const active = recorder
    active.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) chunks.push(event.data)
    }
    settle = new Promise<Blob | null>((resolve) => {
      active.onstop = () => {
        const blob = discarding || !chunks.length
          ? null
          : new Blob(chunks, { type: active.mimeType || 'audio/webm' })
        chunks = []
        release()
        resolve(blob)
      }
      active.onerror = () => {
        error.value = '录音过程中出现问题，请重试'
      }
    })

    seconds.value = 0
    state.value = 'recording'
    try {
      active.start()
    } catch {
      release()
      reset()
      error.value = '无法开始录音，请检查麦克风后重试'
      return false
    }
    ticker = setInterval(() => {
      seconds.value += 1
      if (seconds.value >= maxSeconds) void stop()
    }, 1000)
    return true
  }

  /** 停止录音并返回整段音频；调用方负责上传，用完调 `reset()`。 */
  function stop(): Promise<Blob | null> {
    if (state.value !== 'recording' || !recorder) return Promise.resolve(null)
    state.value = 'transcribing'
    if (ticker !== undefined) {
      clearInterval(ticker)
      ticker = undefined
    }
    recorder.stop()
    return settle ?? Promise.resolve(null)
  }

  /** 取消录音：不产出音频，也不上传。 */
  function cancel() {
    discarding = true
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    } else {
      release()
    }
    reset()
  }

  // 只在组件里注册卸载清理；纯函数式调用（单测）不会因此产生警告。
  if (getCurrentInstance()) onBeforeUnmount(cancel)

  return { state, seconds, error, supported, start, stop, cancel, reset }
}