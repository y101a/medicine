import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { mediaErrorMessage, useVoiceRecorder, VOICE_MAX_SECONDS } from './useVoiceRecorder'

/**
 * 录音状态机的单测。
 *
 * jsdom 没有 `MediaRecorder` 与 `getUserMedia`，所以这里替换掉这两个浏览器 API，
 * 只验证我们自己的逻辑：错误翻译、状态流转、上限自动停止、取消不产出音频。
 */
class FakeRecorder {
  static isTypeSupported = vi.fn((_type: string) => true)
  static lastOptions: { mimeType?: string } | undefined
  state: 'inactive' | 'recording' = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(_stream: unknown, options?: { mimeType?: string }) {
    FakeRecorder.lastOptions = options
    if (options?.mimeType) this.mimeType = options.mimeType
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['voice-bytes'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

function installMedia(behavior: { failWith?: { name: string } } = {}) {
  const stopTrack = vi.fn()
  const getUserMedia = vi.fn(async () => {
    if (behavior.failWith) throw behavior.failWith
    return { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
  })
  Object.defineProperty(window.navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  })
  return { getUserMedia, stopTrack }
}

beforeEach(() => {
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  FakeRecorder.isTypeSupported = vi.fn((_type: string) => true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('语音录音状态机', () => {
  it('权限被拒绝时给出中文提示，且不进入录音状态', async () => {
    installMedia({ failWith: { name: 'NotAllowedError' } })
    const recorder = useVoiceRecorder()
    expect(await recorder.start()).toBe(false)
    expect(recorder.error.value).toContain('麦克风权限被拒绝')
    expect(recorder.state.value).toBe('idle')
  })

  it('没有可用麦克风时提示，不暴露浏览器原始报错', async () => {
    installMedia({ failWith: { name: 'NotFoundError' } })
    const recorder = useVoiceRecorder()
    expect(await recorder.start()).toBe(false)
    expect(recorder.error.value).toBe('没有检测到可用的麦克风')
  })

  it('浏览器不支持录音时建议改用输入法语音输入', async () => {
    installMedia()
    vi.stubGlobal('MediaRecorder', undefined)
    const recorder = useVoiceRecorder()
    expect(await recorder.start()).toBe(false)
    expect(recorder.error.value).toContain('不支持录音')
    expect(recorder.error.value).toContain('输入法语音输入')
  })

  it('停止录音返回整段音频，重置后回到待录状态', async () => {
    const { stopTrack } = installMedia()
    const recorder = useVoiceRecorder()
    expect(await recorder.start()).toBe(true)
    expect(recorder.state.value).toBe('recording')

    const audio = await recorder.stop()
    expect(audio).toBeInstanceOf(Blob)
    expect(audio?.size).toBeGreaterThan(0)
    expect(recorder.state.value).toBe('transcribing')
    expect(stopTrack).toHaveBeenCalled()

    recorder.reset()
    expect(recorder.state.value).toBe('idle')
    expect(recorder.seconds.value).toBe(0)
  })

  it('申请权限期间处于等待授权状态，用户看不到「没反应」', async () => {
    Object.defineProperty(window.navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(() => new Promise(() => {})) },
    })
    const recorder = useVoiceRecorder()
    void recorder.start()
    await Promise.resolve()
    expect(recorder.state.value).toBe('requesting')
  })

  it('优先选择 opus 编码，浏览器只支持一种时按其能力降级', async () => {
    installMedia()
    FakeRecorder.isTypeSupported = vi.fn((type: string): boolean => type === 'audio/webm')
    const recorder = useVoiceRecorder()
    await recorder.start()
    expect(FakeRecorder.lastOptions?.mimeType).toBe('audio/webm')
    recorder.cancel()
  })

  it('组件卸载时释放麦克风轨道', async () => {
    const { stopTrack } = installMedia()
    let recorder: ReturnType<typeof useVoiceRecorder> | undefined
    const Host = defineComponent({
      setup() {
        recorder = useVoiceRecorder()
        return () => h('div')
      },
    })
    const wrapper = mount(Host)
    await recorder!.start()
    wrapper.unmount()
    expect(stopTrack).toHaveBeenCalled()
    expect(recorder!.state.value).toBe('idle')
  })

  it('达到 60 秒上限时自动停止，用户不必手动点', async () => {
    vi.useFakeTimers()
    installMedia()
    const recorder = useVoiceRecorder()
    await recorder.start()
    await vi.advanceTimersByTimeAsync(VOICE_MAX_SECONDS * 1000)
    expect(recorder.seconds.value).toBe(VOICE_MAX_SECONDS)
    expect(recorder.state.value).toBe('transcribing')
  })

  it('取消录音不产出音频，也不会把麦克风一直占用', async () => {
    const { stopTrack } = installMedia()
    const recorder = useVoiceRecorder()
    await recorder.start()
    recorder.cancel()
    expect(recorder.state.value).toBe('idle')
    expect(stopTrack).toHaveBeenCalled()
    expect(await recorder.stop()).toBeNull()
  })

  it('错误翻译只认已知的浏览器错误名，其余走兜底文案', () => {
    expect(mediaErrorMessage({ name: 'NotReadableError' })).toContain('被其他程序占用')
    expect(mediaErrorMessage({ name: 'SomethingElse' })).toBe('无法开始录音，请检查麦克风后重试')
  })
})