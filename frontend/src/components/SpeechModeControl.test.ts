import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import SpeechModeControl from './SpeechModeControl.vue'
import { DEFAULT_SPEECH_PRESET, DEFAULT_SPEECH_RATE } from '../types/speech'
import type { SpeechPreset } from '../types/speech'

/**
 * 语音对话模式的独立入口（用户 2026-10-02：从「+」菜单里分离出来）。
 * 契约 §6.3 的边界在这里也要成立：默认关闭、只有用户点击才开启、不显示音色/语速时不占位置。
 */
const props = {
  speechMode: false,
  presets: [] as SpeechPreset[],
  preset: DEFAULT_SPEECH_PRESET,
  rate: DEFAULT_SPEECH_RATE,
  presetsNotice: '',
}

function mountControl(overrides: Partial<typeof props> = {}) {
  return mount(SpeechModeControl, {
    props: { ...props, ...overrides },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('语音对话模式入口', () => {
  it('默认关闭：按钮 aria-pressed=false，面板里只有「开启」，不显示音色与语速', async () => {
    const wrapper = mountControl()
    const button = wrapper.get('.speech-mode-button')
    expect(button.attributes('aria-pressed')).toBe('false')

    await button.trigger('click')
    await nextTick()
    expect(document.querySelector('.speech-settings-panel')).toBeTruthy()
    expect(document.querySelector('.speech-mode-enable')).toBeTruthy()
    expect(document.querySelector('.speech-preset-select')).toBeNull()
    expect(document.querySelector('.speech-rate-select')).toBeNull()
    expect(document.querySelector('.speech-settings-panel')?.textContent).toContain('不会持续监听')
    wrapper.unmount()
  })

  it('开启后才出现音色与语速，并显示明确的「关闭模式」', async () => {
    const wrapper = mountControl({ speechMode: true })
    const button = wrapper.get('.speech-mode-button')
    expect(button.attributes('aria-pressed')).toBe('true')

    await button.trigger('click')
    await nextTick()
    expect(document.querySelector('.speech-preset-select')).toBeTruthy()
    expect(document.querySelector('.speech-rate-select')).toBeTruthy()
    expect(document.querySelector('.speech-mode-disable')?.textContent).toBe('关闭模式')
    wrapper.unmount()
  })

  it('开关与音色/语速都只上抛事件，组件自己不保存状态', async () => {
    const off = mountControl()
    await off.get('.speech-mode-button').trigger('click')
    await nextTick()
    document.querySelector<HTMLButtonElement>('.speech-mode-enable')?.click()
    await nextTick()
    expect(off.emitted('enable')).toHaveLength(1)
    off.unmount()
    document.body.innerHTML = ''

    const on = mountControl({ speechMode: true })
    await on.get('.speech-mode-button').trigger('click')
    await nextTick()
    document.querySelector<HTMLButtonElement>('.speech-mode-disable')?.click()
    await nextTick()
    expect(on.emitted('disable')).toHaveLength(1)

    const rate = document.querySelector<HTMLSelectElement>('.speech-rate-select')
    expect(rate, '开启态应能选语速').toBeTruthy()
    if (rate) {
      rate.value = '1.2'
      rate.dispatchEvent(new Event('change'))
    }
    await nextTick()
    expect(on.emitted('update:rate')?.[0]).toEqual([1.2])
    on.unmount()
  })

  it('预设列表拉不到时原样透出服务端的兜底提示', async () => {
    const wrapper = mountControl({ speechMode: true, presetsNotice: '音色列表暂时不可用，先用普通话' })
    await wrapper.get('.speech-mode-button').trigger('click')
    await nextTick()
    expect(document.querySelector('.speech-presets-notice')?.textContent).toContain('音色列表暂时不可用')
    wrapper.unmount()
  })
})