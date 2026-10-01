import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { AxiosError, type AxiosRequestConfig } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import HomeView from './HomeView.vue'
import { useAuthStore } from '../stores/auth'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { attachmentsApi } from '../api/attachments'
import { imageGenerationsApi } from '../api/imageGenerations'
import { documentGenerationsApi } from '../api/documentGenerations'
import { voiceApi } from '../api/voice'
import http, { ApiError } from '../api/http'
import { speechApi, speechErrorMessage } from '../api/speech'
import { useSpeechOutput } from '../composables/useSpeechOutput'
import { clearPendingSpeech } from '../composables/pendingSpeech'
import { SPEECH_PRESET_STORAGE_KEY, SPEECH_RATE_STORAGE_KEY } from '../stores/speechPreference'
import { SPEECH_MAX_TEXT_CHARS } from '../types/speech'
import type { Message } from '../types/consultations'

/**
 * 语音输出（TTS）前端（方案 `VOICE_OUTPUT_PLAN.md` §6）。
 *
 * 三层都测到：
 * 1. `speechApi` 的**真实** axios 调用形状（假 adapter 抓请求，证明只发产品枚举、按 Blob 收）；
 * 2. 播放器状态机（注入假播放器与假网络，证明单播放器、抢占、取消与自动播放降级）；
 * 3. 对话页接线（接口桩，证明朗读入口、自然语言触发、语音模式与开麦抢占）。
 *
 * **后端尚未落地**：这里证明的是「前端按契约调用与渲染」，真实链路（真实音频）必须另外单独标注验证。
 */

vi.mock('../api/consultations', () => ({ consultationsApi: {
  create: vi.fn(), send: vi.fn(), stream: vi.fn(), get: vi.fn(), messages: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/models', () => ({ modelsApi: { list: vi.fn() } }))
vi.mock('../api/voice', () => ({ voiceApi: { transcribe: vi.fn() } }))
vi.mock('../api/attachments', () => ({ attachmentsApi: {
  upload: vi.fn(), uploadImage: vi.fn(), content: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/imageGenerations', () => ({
  IMAGE_GENERATION_NOTICE_VERSION: 'image-generation-v1',
  imageGenerationsApi: {
    create: vi.fn(), get: vi.fn(), list: vi.fn(), content: vi.fn(), remove: vi.fn(),
  },
}))
vi.mock('../api/documentGenerations', () => ({
  DOCUMENT_GENERATION_NOTICE_VERSION: 'document-generation-v1',
  documentGenerationsApi: {
    create: vi.fn(), createWithTemplate: vi.fn(), get: vi.fn(), list: vi.fn(), content: vi.fn(), remove: vi.fn(),
  },
}))
/** 录音状态由用例控制：默认「不支持」，专门的用例再打开（不需要真的麦克风）。 */
const recorderState = { current: 'idle' as string, supported: false }
vi.mock('../composables/useVoiceRecorder', async () => {
  const { ref } = await import('vue')
  const state = ref('idle')
  return {
    useVoiceRecorder: () => ({
      state,
      seconds: ref(0),
      error: ref(''),
      supported: recorderState.supported,
      start: vi.fn(async () => { state.value = 'recording'; recorderState.current = 'recording'; return true }),
      stop: vi.fn(async () => null),
      cancel: vi.fn(() => { state.value = 'idle' }),
      reset: vi.fn(() => { state.value = 'idle' }),
    }),
  }
})

const PRESETS = {
  default: 'mandarin_female',
  items: [
    { id: 'mandarin_female', label: '普通话·自然女声', language: 'zh-CN', dialect: null },
    { id: 'cantonese', label: '广东话', language: 'zh-CN', dialect: 'cantonese' },
  ],
}

const conversation = {
  id: 'c1', title: '头痛', messageCount: 2, createdAt: '2026-10-01', updatedAt: '2026-10-01',
}
const userMessage: Message = {
  id: 'u1', role: 'user', content: '最近总是头痛', sequence: 1, createdAt: '2026-10-01T10:00:00Z',
}
const completedAnswer: Message = {
  id: 'a1', role: 'assistant', content: '头痛的常见原因包括……仅供健康科普参考。', sequence: 2,
  generationStatus: 'completed', createdAt: '2026-10-01T10:00:10Z',
}
const stoppedAnswer: Message = {
  ...completedAnswer, id: 'a2', content: '（回答已停止生成）', generationStatus: 'stopped',
}

/** 假播放器：jsdom 不会解码音频，`play/pause` 必须由测试提供。 */
function fakeAudio(play: () => Promise<void> = async () => undefined) {
  return {
    src: '',
    onended: null as null | (() => void),
    onerror: null as null | (() => void),
    play: vi.fn(play),
    pause: vi.fn(),
  } as unknown as HTMLAudioElement
}

describe('speechApi 契约（真实 axios 实例 + 假 adapter）', () => {
  it('只发产品枚举：POST 到消息语音接口、body 只有 speechPreset 与 rate、按 Blob 收', async () => {
    const seen: AxiosRequestConfig[] = []
    const original = http.defaults.adapter
    http.defaults.adapter = async (config) => {
      seen.push(config)
      return { data: new Blob(['mp3'], { type: 'audio/mpeg' }), status: 200, statusText: 'OK', headers: {}, config }
    }
    try {
      // 这个实例是鉴权请求的基础：Cookie 必须带上，否则服务端无法做归属校验。
      expect(http.defaults.withCredentials).toBe(true)
      const blob = await speechApi.synthesize('c1', 'a1', 'cantonese', 1.0)
      expect(blob).toBeInstanceOf(Blob)
    } finally {
      http.defaults.adapter = original
    }

    const config = seen[0]
    expect(config.url).toBe('/consultations/c1/messages/a1/speech')
    expect(config.method).toBe('post')
    expect(config.responseType).toBe('blob')
    expect(JSON.parse(String(config.data))).toEqual({ speechPreset: 'cantonese', rate: 1 })
    // 客户端不能提交待朗读长文本，也不能注入供应商参数。
    const body = JSON.parse(String(config.data)) as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['rate', 'speechPreset'])
    expect('voice' in body).toBe(false)
    expect('instruction' in body).toBe(false)
    expect('text' in body).toBe(false)
  })

  it('429 映射成受控中文，不把错误体里的 HTML/JSON 透给用户', async () => {
    const original = http.defaults.adapter
    http.defaults.adapter = async (config) => {
      throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, undefined, {
        data: new Blob(['<html>{"detail":"internal"}</html>'], { type: 'text/html' }),
        status: 429,
        statusText: 'Too Many Requests',
        headers: {},
        config,
      })
    }
    try {
      await expect(speechApi.synthesize('c1', 'a1', 'mandarin_female', 1.0)).rejects.toMatchObject({
        status: 429,
      })
    } finally {
      http.defaults.adapter = original
    }

    const message = speechErrorMessage(new ApiError('请求过于频繁，请稍后再试', 'HTTP_429', 429))
    expect(message).toBe('语音生成过于频繁，请稍后再试')
    for (const text of [message]) {
      expect(text).not.toMatch(/[<>{}[\]]/)
      expect(text).not.toContain('detail')
    }
    expect(speechErrorMessage(new ApiError('x', 'HTTP_502', 502))).toBe('语音服务暂时不可用，请稍后再试')
    expect(speechErrorMessage(new ApiError('x', 'HTTP_504', 504))).toBe('语音生成超时，请稍后再试')
    // 409 在服务端既是「回答尚未完成」也是「同一条正在生成语音」，文案必须两种情况都成立。
    expect(speechErrorMessage(new ApiError('x', 'SPEECH_MESSAGE_BUSY', 409)))
      .toBe('这条回答暂时无法朗读，请稍后再试')
    expect(speechErrorMessage(new ApiError('x', 'SPEECH_MESSAGE_NOT_READY', 409)))
      .toBe('这条回答暂时无法朗读，请稍后再试')
  })
})

describe('语音输出播放器（useSpeechOutput）', () => {
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>

  beforeEach(() => {
    createObjectURL = vi.fn(() => 'blob:speech-1')
    revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true })
    localStorage.clear()
  })

  function setup(play = async () => undefined) {
    const audio = fakeAudio(play)
    const synthesize = vi.fn(async () => new Blob(['mp3'], { type: 'audio/mpeg' }))
    const player = useSpeechOutput({
      createAudio: () => audio,
      synthesize,
      loadPresets: async () => PRESETS,
    })
    return { player, audio, synthesize }
  }

  it('播放：请求一次、创建 Object URL、进入 playing；同一条消息再点只是续播', async () => {
    const { player, audio, synthesize } = setup()
    await player.loadPresets()

    await player.play({ consultationId: 'c1', messageId: 'a1', text: '头痛的常见原因' })
    expect(synthesize).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(audio.play).toHaveBeenCalledTimes(1)
    expect(player.stateFor('a1')).toBe('playing')

    // 播放中再点「播放」不应重新合成（重复请求就是重复计费）。
    await player.play({ consultationId: 'c1', messageId: 'a1', text: '头痛的常见原因' })
    expect(synthesize).toHaveBeenCalledTimes(1)
    expect(player.stateFor('a1')).toBe('playing')
  })

  it('播放另一条消息会先停掉旧的并释放 Object URL', async () => {
    const { player, audio, synthesize } = setup()
    await player.loadPresets()
    await player.play({ consultationId: 'c1', messageId: 'a1', text: '第一条' })

    await player.play({ consultationId: 'c1', messageId: 'a2', text: '第二条' })

    expect(audio.pause).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:speech-1')
    expect(synthesize).toHaveBeenCalledTimes(2)
    expect(player.stateFor('a1')).toBe('idle')
    expect(player.stateFor('a2')).toBe('playing')
  })

  it('暂停 / 继续 / 停止：状态与释放都对', async () => {
    const { player, audio } = setup()
    await player.loadPresets()
    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })

    player.pause()
    expect(audio.pause).toHaveBeenCalledTimes(1)
    expect(player.stateFor('a1')).toBe('paused')

    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })
    expect(audio.play).toHaveBeenCalledTimes(2)
    expect(player.stateFor('a1')).toBe('playing')

    player.stop()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:speech-1')
    expect(player.stateFor('a1')).toBe('idle')
    expect(player.errorFor('a1')).toBe('')
  })

  it('浏览器拒绝自动播放：降级为 ready 且不报错，点击播放不重新请求', async () => {
    const blocked = Object.assign(new Error('blocked'), { name: 'NotAllowedError' })
    const { player, synthesize, audio } = setup(async () => { throw blocked })
    await player.loadPresets()

    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })

    expect(player.stateFor('a1')).toBe('ready')
    expect(player.errorFor('a1')).toBe('')
    expect(player.autoplayBlocked.value).toBe(true)

    // 用户点「点击播放」：复用已经拿到的音频，不再打一次接口。
    ;(audio.play as ReturnType<typeof vi.fn>).mockResolvedValue(undefined)
    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })
    expect(synthesize).toHaveBeenCalledTimes(1)
    expect(player.stateFor('a1')).toBe('playing')
  })

  it('明显超长的回答本地先拦下，不发请求', async () => {
    const { player, synthesize } = setup()
    await player.loadPresets()

    await player.play({
      consultationId: 'c1',
      messageId: 'a1',
      text: '字'.repeat(SPEECH_MAX_TEXT_CHARS + 1),
    })

    expect(synthesize).not.toHaveBeenCalled()
    expect(player.errorFor('a1')).toBe('内容较长，请分段朗读')
  })

  it('服务端 502/504 与用户取消的文案', async () => {
    const failing = vi.fn(async () => { throw new ApiError('坏网关', 'HTTP_502', 502) })
    const player = useSpeechOutput({ createAudio: () => fakeAudio(), synthesize: failing, loadPresets: async () => PRESETS })
    await player.loadPresets()
    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })
    expect(player.errorFor('a1')).toBe('语音服务暂时不可用，请稍后再试')

    const cancelled = vi.fn(async () => { throw new ApiError('请求已取消', 'REQUEST_CANCELLED') })
    const quiet = useSpeechOutput({ createAudio: () => fakeAudio(), synthesize: cancelled, loadPresets: async () => PRESETS })
    await quiet.loadPresets()
    await quiet.play({ consultationId: 'c1', messageId: 'a1', text: '正文' })
    expect(quiet.errorFor('a1')).toBe('')
    expect(quiet.stateFor('a1')).toBe('idle')
  })

  it('预设列表拉不到时只保留普通话兜底；存过的方言不在白名单时退回默认', async () => {
    localStorage.setItem(SPEECH_PRESET_STORAGE_KEY, 'cantonese')
    const offline = useSpeechOutput({
      createAudio: () => fakeAudio(),
      synthesize: vi.fn(),
      loadPresets: async () => { throw new Error('404') },
    })
    await offline.loadPresets()
    expect(offline.presets.value.map(item => item.id)).toEqual(['mandarin_female'])
    expect(offline.preset.value).toBe('mandarin_female')
    expect(offline.presetsNotice.value).toContain('普通话')

    const online = useSpeechOutput({
      createAudio: () => fakeAudio(),
      synthesize: vi.fn(),
      loadPresets: async () => PRESETS,
    })
    await online.loadPresets()
    // 白名单里确实有粤语，就沿用用户存过的选择。
    expect(online.preset.value).toBe('cantonese')
  })

  it('请求用当前选中的预设与语速（方言口头请求只覆盖本轮，不改默认）', async () => {
    localStorage.setItem(SPEECH_RATE_STORAGE_KEY, '1.2')
    const { player, synthesize } = setup()
    await player.loadPresets()
    expect(player.rate.value).toBe(1.2)

    await player.play({ consultationId: 'c1', messageId: 'a1', text: '正文', presetOverride: 'cantonese' })
    expect(synthesize).toHaveBeenLastCalledWith('c1', 'a1', 'cantonese', 1.2, expect.anything())
    // 本轮覆盖不写偏好。
    expect(player.preset.value).toBe('mandarin_female')
    expect(localStorage.getItem(SPEECH_PRESET_STORAGE_KEY)).toBeNull()
  })
})

describe('对话页接线（HomeView）', () => {
  let wrapper: VueWrapper | undefined

  async function setup(path = '/app/chat', messages?: Message[]) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = {
      id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user',
      phoneVerified: true, registeredAt: '2026-10-01',
    }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/app/chat', component: HomeView },
        { path: '/app/consultations/:id', name: 'consultation', component: HomeView },
      ],
    })
    await router.push(path)
    if (messages) {
      vi.mocked(consultationsApi.messages).mockResolvedValue({ items: messages, hasMore: false })
    }
    wrapper = mount({ template: '<router-view :key="$route.fullPath" />' }, {
      attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] },
    })
    await flushPromises()
    await flushPromises()
    return wrapper
  }

  async function sendMessage(target: VueWrapper, text: string) {
    await target.get('textarea').setValue(text)
    await target.get('form.composer').trigger('submit')
    await flushPromises()
  }

  function speechButtons(): HTMLButtonElement[] {
    return Array.from(document.querySelectorAll<HTMLButtonElement>('.speech-button'))
  }
  function buttonByText(text: string): HTMLButtonElement | undefined {
    return speechButtons().find(button => button.textContent?.includes(text))
  }
  function statusText(): string {
    return document.querySelector('.speech-status')?.textContent || ''
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    // 待播队列是模块级状态：不清会让上一个用例的请求漏到下一个用例。
    clearPendingSpeech()
    recorderState.supported = false
    recorderState.current = 'idle'
    vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
    vi.mocked(consultationsApi.send).mockResolvedValue(userMessage)
    vi.mocked(consultationsApi.stream).mockResolvedValue(completedAnswer)
    vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [], hasMore: false })
    vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
    vi.mocked(modelsApi.list).mockResolvedValue([
      { id: 'm1', name: '测试模型', provider: 'deepseek', providerName: 'DeepSeek', description: '', isDefault: true, keySource: 'server' },
    ])
    vi.mocked(attachmentsApi.list).mockResolvedValue([])
    vi.mocked(imageGenerationsApi.list).mockResolvedValue([])
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([])
    vi.mocked(voiceApi.transcribe).mockResolvedValue({ text: '', durationMs: 0 })
    vi.spyOn(speechApi, 'presets').mockResolvedValue(PRESETS)
    vi.spyOn(speechApi, 'synthesize').mockResolvedValue(new Blob(['mp3'], { type: 'audio/mpeg' }))
    Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:speech'), configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true })
    // jsdom 不会解码音频：这里把播放能力换成可控实现（真实行为由浏览器负责）。
    Object.defineProperty(HTMLMediaElement.prototype, 'play', {
      value: vi.fn().mockResolvedValue(undefined), configurable: true,
    })
    Object.defineProperty(HTMLMediaElement.prototype, 'pause', { value: vi.fn(), configurable: true })
    HTMLElement.prototype.scrollTo = vi.fn()
  })

  afterEach(() => {
    // 必须真的卸载：否则上一个用例的实例还活着，它的 watcher 会继续消费模块级的待播队列，
    // 把本用例排队的自动朗读吞掉（表现为「开了语音模式却没有语音请求」）。
    wrapper?.unmount()
    wrapper = undefined
    document.body.innerHTML = ''
  })

  it('只有已完成且有正文的助手回答有朗读入口', async () => {
    await setup('/app/consultations/c1', [userMessage, completedAnswer, stoppedAnswer])
    await nextTick()

    // 用户消息没有入口：整页只有一条消息带朗读控件。
    expect(document.querySelectorAll('.speech-control').length).toBe(1)
    expect(buttonByText('朗读')).toBeTruthy()
    expect(document.querySelector('.user-message')?.textContent).toContain('最近总是头痛')
  })

  it('点朗读：按助手消息 id 调接口，状态变成正在朗读', async () => {
    await setup('/app/consultations/c1', [userMessage, completedAnswer])
    await nextTick()

    buttonByText('朗读')?.click()
    await flushPromises()

    expect(speechApi.synthesize).toHaveBeenCalledTimes(1)
    const [cid, messageId, preset, rate] = vi.mocked(speechApi.synthesize).mock.calls[0]
    expect(cid).toBe('c1')
    expect(messageId).toBe('a1')
    expect(preset).toBe('mandarin_female')
    expect(rate).toBe(1)
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(statusText()).toContain('正在朗读')
    expect(buttonByText('暂停')).toBeTruthy()

    buttonByText('停止')?.click()
    await flushPromises()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:speech')
    expect(buttonByText('朗读')).toBeTruthy()
  })

  it('自然语言意图：先出完文字，再用服务端给的方言请求音频', async () => {
    vi.mocked(consultationsApi.send).mockResolvedValue({
      ...userMessage, id: 'u2', speechOutputIntent: { requested: true, speechPreset: 'cantonese' },
    })
    await setup('/app/chat')
    const order: string[] = []
    vi.mocked(consultationsApi.stream).mockImplementation(async () => {
      order.push('stream')
      return completedAnswer
    })
    vi.mocked(speechApi.synthesize).mockImplementation(async () => {
      order.push('speech')
      return new Blob(['mp3'], { type: 'audio/mpeg' })
    })

    await sendMessage(wrapper as VueWrapper, '请用粤语读出来')

    expect(order).toEqual(['stream', 'speech'])
    expect(vi.mocked(speechApi.synthesize).mock.calls[0][2]).toBe('cantonese')
    // 文字回答确实生成过（音频只在文字完成之后才请求，见上面的 order）。
    expect(consultationsApi.stream).toHaveBeenCalledTimes(1)
  })

  it('语音对话模式：默认隐藏设置，开启后上拉，可收起或在面板内关闭', async () => {
    await setup('/app/chat')
    await sendMessage(wrapper as VueWrapper, '头痛怎么办')
    expect(speechApi.synthesize).not.toHaveBeenCalled()

    const modeButton = Array.from(document.querySelectorAll<HTMLButtonElement>('.speech-mode-button'))[0]
    expect(modeButton.getAttribute('aria-pressed')).toBe('false')
    expect(document.querySelector('.speech-settings-panel')).toBeNull()
    expect(document.querySelector('.speech-preset-select')).toBeNull()
    modeButton.click()
    await nextTick()
    expect(modeButton.getAttribute('aria-pressed')).toBe('true')
    expect(modeButton.getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('.speech-settings-panel')).toBeTruthy()
    expect(document.querySelector('.speech-preset-select')).toBeTruthy()
    expect(document.querySelector('.speech-rate-select')).toBeTruthy()

    // 开启后耳机只控制设置面板，不会因为收起面板而误关自动朗读。
    modeButton.click()
    await nextTick()
    expect(modeButton.getAttribute('aria-pressed')).toBe('true')
    expect(document.querySelector('.speech-settings-panel')).toBeNull()
    modeButton.click()
    await nextTick()
    document.querySelector<HTMLButtonElement>('.speech-mode-disable')?.click()
    await nextTick()
    expect(modeButton.getAttribute('aria-pressed')).toBe('false')
    expect(document.querySelector('.speech-settings-panel')).toBeNull()

    // 再开启，证明关闭后仍可恢复，并沿用原来的自动朗读链路。
    modeButton.click()
    await nextTick()

    await sendMessage(wrapper as VueWrapper, '再讲讲注意事项')
    await flushPromises()
    expect(speechApi.synthesize).toHaveBeenCalledTimes(1)
  })

  it('浏览器拒绝自动播放：显示「语音已生成，点击播放」，点它不重新请求', async () => {
    const blocked = Object.assign(new Error('blocked'), { name: 'NotAllowedError' })
    Object.defineProperty(HTMLMediaElement.prototype, 'play', {
      value: vi.fn().mockRejectedValue(blocked), configurable: true,
    })
    await setup('/app/chat', [userMessage, completedAnswer])
    // 模式开关必须由用户点击（契约 §6.3：默认关闭）。
    Array.from(document.querySelectorAll<HTMLButtonElement>('.speech-mode-button'))[0].click()
    await nextTick()

    await sendMessage(wrapper as VueWrapper, '头痛怎么办')
    await flushPromises()
    // 排队 → 新实例接手 → 请求 → 播放被拒 → 状态刷新，需要多一次渲染 tick。
    await nextTick()
    // 新会话首条消息会 router.replace 重挂载组件：排队的自动朗读由新实例接手，
    // 而重挂载后的消息列表来自 `messages` 接口（这里已经桩成同一条回答）。
    expect(statusText()).toContain('语音已生成，点击播放')
    expect(document.body.textContent).not.toContain('系统错误')
    const callCount = vi.mocked(speechApi.synthesize).mock.calls.length
    buttonByText('点击播放')?.click()
    await flushPromises()
    expect(vi.mocked(speechApi.synthesize).mock.calls.length).toBe(callCount)
  })

  it('开麦克风录音前先停止朗读', async () => {
    recorderState.supported = true
    localStorage.setItem('medical-assistant:voice-consent-seen', 'true')
    await setup('/app/consultations/c1', [userMessage, completedAnswer])
    await nextTick()
    buttonByText('朗读')?.click()
    await flushPromises()
    expect(vi.mocked(HTMLMediaElement.prototype.pause)).not.toHaveBeenCalled()

    document.querySelector<HTMLButtonElement>('.voice-button')?.click()
    await flushPromises()

    expect(vi.mocked(HTMLMediaElement.prototype.pause)).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:speech')
  })

  it('生成失败只显示受控中文，不泄露错误体', async () => {
    vi.mocked(speechApi.synthesize).mockRejectedValue(new ApiError('坏网关', 'HTTP_502', 502))
    await setup('/app/consultations/c1', [userMessage, completedAnswer])
    await nextTick()

    buttonByText('朗读')?.click()
    await flushPromises()

    expect(statusText()).toContain('语音服务暂时不可用，请稍后再试')
    expect(statusText()).not.toMatch(/[<>{}[\]]/)
  })
})
