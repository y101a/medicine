import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import HealthRecordView from './HealthRecordView.vue'
import { healthRecordsApi } from '../api/healthRecords'
import type { HealthRecord } from '../types/healthRecords'

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

const baseSettings = { collectionEnabled: true, noticeSeen: true, recordCount: 2 }

const symptom: HealthRecord = {
  id: 'r-symptom',
  category: 'symptom',
  categoryLabel: '近期症状',
  content: '夜间失眠',
  source: 'conversation',
  recordedAt: '2026-09-16T10:00:00Z',
  updatedAt: '2026-09-16T10:00:00Z',
}

const allergy: HealthRecord = {
  id: 'r-allergy',
  category: 'allergy',
  categoryLabel: '过敏史',
  content: '对青霉素过敏',
  source: 'user',
  recordedAt: '2026-09-15T10:00:00Z',
  updatedAt: '2026-09-15T10:00:00Z',
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...baseSettings })
  vi.mocked(healthRecordsApi.list).mockResolvedValue([symptom, allergy])
  vi.mocked(healthRecordsApi.create).mockResolvedValue(symptom)
  vi.mocked(healthRecordsApi.update).mockResolvedValue(symptom)
  vi.mocked(healthRecordsApi.remove).mockResolvedValue(undefined)
  vi.mocked(healthRecordsApi.updateSettings).mockResolvedValue({ ...baseSettings })
})

afterEach(() => {
  document.body.innerHTML = ''
})

async function mountView() {
  const wrapper = mount(HealthRecordView, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('健康记录页', () => {
  it('按分类分组展示记录，并标注来源与时间', async () => {
    const wrapper = await mountView()

    expect(document.body.textContent).toContain('近期症状')
    expect(document.body.textContent).toContain('过敏史')
    expect(document.body.textContent).toContain('夜间失眠')
    expect(document.body.textContent).toContain('对青霉素过敏')
    expect(document.body.textContent).toContain('对话自动记录')
    expect(document.body.textContent).toContain('你手动添加或修改')
    expect(healthRecordsApi.list).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('明确说明记录只是背景资料，不是诊断结论', async () => {
    const wrapper = await mountView()
    expect(document.body.textContent).toContain('不是诊断结论')
    expect(document.body.textContent).toContain('不能替代医生面诊')
    wrapper.unmount()
  })

  it('空内容不允许提交，添加后清空输入', async () => {
    const wrapper = await mountView()
    const input = document.querySelector<HTMLInputElement>('.health-records__input input')
    expect(input).not.toBeNull()
    const addButton = document.querySelector<HTMLButtonElement>(
      '.health-records__form .el-button--primary',
    )
    expect(addButton?.disabled).toBe(true)

    if (input) {
      input.value = '最近经常口渴'
      input.dispatchEvent(new Event('input'))
    }
    await flushPromises()
    expect(addButton?.disabled).toBe(false)

    addButton?.click()
    await flushPromises()
    expect(healthRecordsApi.create).toHaveBeenCalledWith({
      category: 'symptom',
      content: '最近经常口渴',
    })
    wrapper.unmount()
  })

  it('修改记录走更新接口而不是新增', async () => {
    const wrapper = await mountView()
    const editButton = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
      (button) => button.textContent?.trim() === '修改',
    )
    expect(editButton).toBeDefined()
    editButton?.click()
    await flushPromises()

    const editor = document.querySelector<HTMLInputElement>('.health-records__item input')
    expect(editor).not.toBeNull()
    if (editor) {
      editor.value = '最近一周夜间失眠'
      editor.dispatchEvent(new Event('input'))
    }
    await flushPromises()

    const saveButton = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
      (button) => button.textContent?.trim() === '保存',
    )
    saveButton?.click()
    await flushPromises()

    expect(healthRecordsApi.update).toHaveBeenCalledWith('r-symptom', {
      content: '最近一周夜间失眠',
    })
    expect(healthRecordsApi.create).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('关闭自动记录后给出明确说明，且仍可查看既有记录', async () => {
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({
      ...baseSettings,
      collectionEnabled: false,
    })
    const wrapper = await mountView()

    expect(document.body.textContent).toContain('对话自动记录已关闭')
    expect(document.body.textContent).toContain('已有记录仍会保留')
    expect(document.body.textContent).toContain('夜间失眠')
    wrapper.unmount()
  })

  it('切换开关会调用设置接口', async () => {
    const wrapper = await mountView()
    const toggle = document.querySelector<HTMLElement>('.health-records__switch')
    expect(toggle).not.toBeNull()
    toggle?.click()
    await flushPromises()

    expect(healthRecordsApi.updateSettings).toHaveBeenCalledWith({ collectionEnabled: false })
    wrapper.unmount()
  })
})