import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import HealthRecordNoticeDialog from './HealthRecordNoticeDialog.vue'
import { healthRecordsApi } from '../api/healthRecords'
import { useHealthRecordsStore } from '../stores/healthRecords'

vi.mock('../api/healthRecords', () => ({
  healthRecordsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    settings: vi.fn(),
    updateSettings: vi.fn(),
    onboarding: vi.fn(),
    extract: vi.fn(),
  },
}))

const baseSettings = { collectionEnabled: true, noticeSeen: false, recordCount: 0 }

function click(selector: string) {
  document.querySelector<HTMLButtonElement>(selector)?.click()
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...baseSettings })
  vi.mocked(healthRecordsApi.updateSettings).mockResolvedValue({
    ...baseSettings,
    noticeSeen: true,
  })
  vi.mocked(healthRecordsApi.onboarding).mockResolvedValue({
    ...baseSettings,
    noticeSeen: true,
    recordCount: 1,
  })
  vi.mocked(healthRecordsApi.list).mockResolvedValue([])
})

afterEach(() => {
  document.body.innerHTML = ''
})

function mountDialog() {
  return mount(HealthRecordNoticeDialog, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
}

describe('健康记录首次通知', () => {
  it('首次检查才弹出通知，且不写入任何记录', async () => {
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()

    expect(await store.checkFirstNotice()).toBe(true)
    await flushPromises()
    expect(document.body.textContent).toContain('只记录你明确说过的内容')
    expect(document.body.textContent).toContain('健康记录不参与紧急症状判断')

    expect(await store.checkFirstNotice()).toBe(false)
    expect(healthRecordsApi.settings).toHaveBeenCalledTimes(1)
    expect(healthRecordsApi.onboarding).not.toHaveBeenCalled()
    expect(healthRecordsApi.updateSettings).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('已确认过通知的用户不再弹出', async () => {
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({
      ...baseSettings,
      noticeSeen: true,
    })
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()

    expect(await store.checkFirstNotice()).toBe(false)
    await flushPromises()
    expect(store.noticeVisible).toBe(false)
    expect(document.body.textContent).not.toContain('只记录你明确说过的内容')
    wrapper.unmount()
  })

  it('跳过只确认已读通知，保持默认采集', async () => {
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()
    await store.checkFirstNotice()
    await flushPromises()

    click('.health-notice__skip')
    await flushPromises()

    expect(healthRecordsApi.updateSettings).toHaveBeenCalledWith({ noticeSeen: true })
    expect(store.noticeVisible).toBe(false)
    expect(healthRecordsApi.onboarding).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('关闭采集在首次通知里当场生效', async () => {
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()
    await store.checkFirstNotice()
    await flushPromises()

    click('.health-notice__disable')
    await flushPromises()

    expect(healthRecordsApi.updateSettings).toHaveBeenCalledWith({
      noticeSeen: true,
      collectionEnabled: false,
    })
    expect(store.noticeVisible).toBe(false)
    wrapper.unmount()
  })

  it('保存会把本人自述的身体状态记为一条记录', async () => {
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()
    await store.checkFirstNotice()
    await flushPromises()

    const input = document.querySelector<HTMLInputElement>('.health-notice__note input')
    expect(input).not.toBeNull()
    if (input) {
      input.value = '最近睡得少'
      input.dispatchEvent(new Event('input'))
    }
    await flushPromises()

    click('.health-notice__submit')
    await flushPromises()

    expect(healthRecordsApi.onboarding).toHaveBeenCalledWith('fair', '最近睡得少')
    expect(store.noticeVisible).toBe(false)
    wrapper.unmount()
  })

  it('接口失败时保留弹窗并提示错误', async () => {
    vi.mocked(healthRecordsApi.onboarding).mockRejectedValue(new Error('boom'))
    const store = useHealthRecordsStore()
    const wrapper = mountDialog()
    await store.checkFirstNotice()
    await flushPromises()

    click('.health-notice__submit')
    await flushPromises()

    expect(store.noticeVisible).toBe(true)
    expect(document.body.textContent).toContain('发生未知错误，请稍后重试')
    wrapper.unmount()
  })
})