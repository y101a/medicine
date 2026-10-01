import { computed, getCurrentInstance, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../api/http'
import { SPEECH_CANCELLED_CODE, speechApi, speechErrorMessage } from '../api/speech'
import {
  DEFAULT_SPEECH_PRESET,
  FALLBACK_SPEECH_PRESETS,
  SPEECH_MAX_TEXT_CHARS,
  type SpeechPlaybackState,
  type SpeechPreset,
  type SpeechRate,
} from '../types/speech'
import {
  pickAvailablePreset,
  readSpeechPreset,
  readSpeechRate,
  rememberSpeechPreset,
  rememberSpeechRate,
} from '../stores/speechPreference'

/**
 * 语音输出的**单播放器**（方案 `VOICE_OUTPUT_PLAN.md` §6.1–§6.3）。
 *
 * 设计要点（每条都有契约依据，别按别的 composable 的写法改）：
 * 1. **全局只有一个播放器**：整页共用一份状态，同一时间只播一段；新播放先停旧的。
 * 2. **不重复请求**：同一条消息已经拿到音频（`ready`/`paused`）时，再点只是续播，
 *    **不重新合成**——重复请求就是重复计费（契约 §6.2「不能重复点击产生并行请求」）。
 * 3. **音频只在内存**：一次 Blob + 一个 Object URL，停止/抢占/切会话/卸载都会 `revokeObjectURL`。
 * 4. **自动播放被拦不算错误**：进入 `ready`，界面改成「语音已生成，点击播放」（契约 §6.2）。
 * 5. **文本只做长度预检**：待朗读文本由服务端按 `messageId` 取，前端传进来的文本
 *    只用来在明显超长时提前拦住，不会被外发（契约 §2.2、§4.2）。
 * 6. 失败**只影响这条语音**：文字回答、引用和其它功能都不受影响（契约 §6.2）。
 */

export interface SpeechOutputDeps {
  /** 播放器工厂：默认 `new Audio()`。单测注入假实现（jsdom 不会解码音频）。 */
  createAudio?: () => HTMLAudioElement
  /** 网络层：默认 `speechApi`；单测注入以免真的打请求。 */
  synthesize?: typeof speechApi.synthesize
  loadPresets?: typeof speechApi.presets
}

export interface SpeechPlayRequest {
  consultationId: string
  messageId: string
  /** 该条助手回答的正文，**只用于本地长度预检**。 */
  text: string
  /** 本轮覆盖预设（用户在对话里明确说了方言）；不写偏好、不影响下次。 */
  presetOverride?: string
}

/** 按 Unicode 码点计数（与服务端 `tts_max_text_chars` 的口径一致，不是 UTF-16 长度）。 */
function unicodeLength(text: string): number {
  return Array.from(text).length
}

export function useSpeechOutput(deps: SpeechOutputDeps = {}) {
  const createAudio = deps.createAudio ?? (() => new Audio())
  // 晚绑定：默认实现按调用时刻从 `speechApi` 上取，测试里 `vi.spyOn` 替换才会生效。
  const synthesize: typeof speechApi.synthesize = deps.synthesize
    ?? ((...args) => speechApi.synthesize(...args))
  const requestPresets: typeof speechApi.presets = deps.loadPresets
    ?? ((...args) => speechApi.presets(...args))

  const state = ref<SpeechPlaybackState>('idle')
  /** 当前（或刚刚失败过的）消息 id：状态与错误只对这条消息显示。 */
  const currentMessageId = ref('')
  const errorMessage = ref('')
  /** 音频拿到了但浏览器不允许自动播放：界面降级为「点击播放」。 */
  const autoplayBlocked = ref(false)

  const presets = ref<SpeechPreset[]>(FALLBACK_SPEECH_PRESETS.items)
  /** 预设是否来自服务端（false 表示用了最小兜底，只保证普通话）。 */
  const presetsFromServer = ref(false)
  const presetsNotice = ref('')
  const preset = ref(DEFAULT_SPEECH_PRESET)
  const rate = ref<SpeechRate>(readSpeechRate())
  const presetLabel = computed(
    () => presets.value.find(item => item.id === preset.value)?.label || '',
  )

  let audio: HTMLAudioElement | undefined
  let objectUrl = ''
  let controller: AbortController | undefined
  let disposed = false

  /** 只停播放并释放字节，不清理消息 id / 错误（错误要继续挂在那条消息上）。 */
  function releaseAudio(): void {
    if (audio) {
      audio.onended = null
      audio.onerror = null
      try {
        audio.pause()
      } catch {
        // 个别浏览器在未开始播放时 pause 会抛错；释放流程不能因此中断。
      }
      audio.src = ''
      audio = undefined
    }
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
      objectUrl = ''
    }
  }

  function abortPendingRequest(): void {
    if (controller) {
      controller.abort()
      controller = undefined
    }
  }

  function reset(): void {
    abortPendingRequest()
    releaseAudio()
    state.value = 'idle'
    autoplayBlocked.value = false
  }

  /** 停止播放并清空当前消息（按钮回到「朗读」，错误提示也一并清掉）。 */
  function stop(): void {
    reset()
    currentMessageId.value = ''
    errorMessage.value = ''
  }

  function fail(messageId: string, message: string): void {
    // 只覆盖同一条消息的错误：新播放已经开始时不能把它的状态改掉。
    if (currentMessageId.value !== messageId) return
    reset()
    currentMessageId.value = messageId
    errorMessage.value = message
  }

  /** 当前选中的预设是否真的可用（服务端列表里没有就退回列表默认值）。 */
  function resolvePreset(override?: string): string {
    const available = presets.value.map(item => item.id)
    if (override && available.includes(override)) return override
    const fallback = presetsFromServer.value ? preset.value : FALLBACK_SPEECH_PRESETS.default
    return pickAvailablePreset(preset.value, available, fallback)
  }

  async function loadPresets(): Promise<void> {
    try {
      const list = await requestPresets()
      const items = (Array.isArray(list?.items) ? list.items : []).filter(item => item?.id)
      if (!items.length) throw new Error('empty preset list')
      if (disposed) return
      presets.value = items
      presetsFromServer.value = true
      presetsNotice.value = ''
      preset.value = pickAvailablePreset(readSpeechPreset(), items.map(item => item.id), list.default)
    } catch {
      // 后端未落地或网络失败：退回最小兜底，朗读入口仍可用（只是没有方言可挑）。
      if (disposed) return
      presets.value = FALLBACK_SPEECH_PRESETS.items
      presetsFromServer.value = false
      presetsNotice.value = '暂时获取不到音色列表，先用普通话朗读'
      preset.value = pickAvailablePreset(
        readSpeechPreset(),
        FALLBACK_SPEECH_PRESETS.items.map(item => item.id),
        FALLBACK_SPEECH_PRESETS.default,
      )
    }
  }

  async function startPlayback(messageId: string): Promise<void> {
    if (!audio) return
    try {
      await audio.play()
      if (disposed || currentMessageId.value !== messageId) return
      state.value = 'playing'
      autoplayBlocked.value = false
      errorMessage.value = ''
    } catch (cause) {
      if (disposed || currentMessageId.value !== messageId) return
      const name = (cause as { name?: string } | null)?.name
      if (name === 'NotAllowedError') {
        // 浏览器自动播放策略：不是故障，降级成用户点一下再播（契约 §6.2）。
        state.value = 'ready'
        autoplayBlocked.value = true
        errorMessage.value = ''
        return
      }
      fail(messageId, '语音播放失败，请稍后重试')
    }
  }

  /**
   * 播放一条助手回答的语音；同一条消息已经有音频时只是**续播**（不重新合成、不重复计费）。
   */
  async function play(request: SpeechPlayRequest): Promise<void> {
    const { consultationId, messageId, text } = request
    if (state.value === 'loading' && currentMessageId.value === messageId) return
    // 同一条消息已经拿到音频（播放中/暂停/待点击播放）：只续播，**不重新合成**。
    // 「不能重复点击产生并行请求」同时意味着不能重复计费（契约 §6.2）。
    if (currentMessageId.value === messageId && state.value !== 'idle') {
      if (state.value !== 'playing') await startPlayback(messageId)
      return
    }
    if (!consultationId) {
      fail(messageId, '会话还没准备好，请稍后再试')
      return
    }
    // 错误与状态先落到这条消息上，后面任何一条早退路径都能把受控短句显示出来。
    reset()
    currentMessageId.value = messageId
    errorMessage.value = ''
    if (unicodeLength(text) > SPEECH_MAX_TEXT_CHARS) {
      // 明显超长就先拦下：服务端也会拒（`SPEECH_TEXT_TOO_LONG`），但没必要白等一次生成。
      fail(messageId, '内容较长，请分段朗读')
      return
    }
    state.value = 'loading'
    const activeController = new AbortController()
    controller = activeController
    try {
      const blob = await synthesize(
        consultationId,
        messageId,
        resolvePreset(request.presetOverride),
        rate.value,
        activeController.signal,
      )
      if (disposed || activeController.signal.aborted || currentMessageId.value !== messageId) return
      controller = undefined
      objectUrl = URL.createObjectURL(blob)
      const player = createAudio()
      player.onended = () => {
        if (currentMessageId.value !== messageId) return
        stop()
      }
      player.onerror = () => fail(messageId, '语音播放失败，请稍后重试')
      player.src = objectUrl
      audio = player
      await startPlayback(messageId)
    } catch (cause) {
      if (disposed) return
      const cancelled = activeController.signal.aborted
        || (cause instanceof ApiError && cause.code === SPEECH_CANCELLED_CODE)
      if (cancelled) {
        // 用户取消/被新播放抢占：静默，不报错。
        if (currentMessageId.value === messageId) reset()
        return
      }
      fail(messageId, speechErrorMessage(cause))
    }
  }

  function pause(): void {
    if (state.value !== 'playing' || !audio) return
    audio.pause()
    state.value = 'paused'
  }

  /** 只对当前播放器生效；传别的消息 id 时忽略（按钮是每条消息一份的）。 */
  function stateFor(messageId: string): SpeechPlaybackState {
    return currentMessageId.value === messageId ? state.value : 'idle'
  }

  function errorFor(messageId: string): string {
    return currentMessageId.value === messageId ? errorMessage.value : ''
  }

  function autoplayBlockedFor(messageId: string): boolean {
    return currentMessageId.value === messageId && autoplayBlocked.value
  }

  function isActive(messageId: string): boolean {
    return currentMessageId.value === messageId && state.value !== 'idle'
  }

  // 预设与语速是本机偏好（不含音频、文本或消息 id）；方言的口头请求不写这里。
  watch(preset, (value) => {
    if (presets.value.some(item => item.id === value)) rememberSpeechPreset(value)
  })
  watch(rate, (value) => rememberSpeechRate(value))

  function dispose(): void {
    disposed = true
    stop()
  }

  // 纯函数式调用（单测）不注册卸载钩子，避免产生 Vue 警告。
  if (getCurrentInstance()) onBeforeUnmount(dispose)

  return {
    state,
    currentMessageId,
    errorMessage,
    autoplayBlocked,
    presets,
    presetsFromServer,
    presetsNotice,
    preset,
    rate,
    presetLabel,
    loadPresets,
    play,
    pause,
    stop,
    stateFor,
    errorFor,
    autoplayBlockedFor,
    isActive,
    dispose,
  }
}