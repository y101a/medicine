import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import SettingsView from './SettingsView.vue'
import { useAuthStore } from '../stores/auth'
import { healthRecordsApi } from '../api/healthRecords'

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
vi.mock('../api/users', () => ({
  usersApi: {
    updateProfile: vi.fn(),
    uploadAvatar: vi.fn(),
    avatarUrl: vi.fn((version: number) => `/api/v1/users/me/avatar?v=${version}`),
  },
}))

const settingsPayload = { collectionEnabled: true, noticeSeen: true, recordCount: 0 }

async function setup(query = '') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = {
    id: 'u1', username: 'tester', realName: '张三', gender: 'private',
    role: 'user', phoneMasked: '138****8000', idCardMasked: '110105********002X',
    registeredAt: '2026-09-01T00:00:00Z',
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/app/settings', name: 'settings', component: SettingsView }],
  })
  await router.push(`/app/settings${query}`)
  await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, {
    attachTo: document.body,
    global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('设置页分栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.replaceChildren()
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...settingsPayload })
    vi.mocked(healthRecordsApi.list).mockResolvedValue([])
  })

  it('默认落在账户信息分栏，并且完全不加载健康记录', async () => {
    const wrapper = await setup()

    expect(document.querySelector('#profile-title')?.textContent).toBe('账户信息')
    expect(document.querySelector('.health-records__title')).toBeNull()
    // 关键行为断言：健康记录分栏是重内容（列表 + 图表），默认分栏下不该白跑接口。
    expect(healthRecordsApi.list).not.toHaveBeenCalled()
    expect(healthRecordsApi.settings).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('带 tab=health 进入时直接落在健康记录分栏', async () => {
    const wrapper = await setup('?tab=health')
    // 该分栏是异步组件，等它真正渲染出来再断言。
    // 超时必须显式放宽：默认 1s 在整套用例并行运行、CPU 紧张时会超时（实测耗时 993ms，贴着上限）。
    await vi.waitFor(
      () => expect(document.querySelector('.health-records__title')).not.toBeNull(),
      { timeout: 5000 },
    )

    expect(healthRecordsApi.list).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('切换分栏后账户信息仍保持挂载，未保存的草稿不丢', async () => {
    const wrapper = await setup()
    await wrapper.get('input[autocomplete="name"]').setValue('未保存的草稿')
    await flushPromises()

    const tabButton = (label: string) => {
      const found = wrapper.findAll('[role="tab"]').find(item => item.text().includes(label))
      expect(found, `应存在「${label}」分栏按钮`).toBeTruthy()
      return found!
    }

    await tabButton('健康记录').trigger('click')
    await vi.waitFor(
      () => expect(document.querySelector('.health-records__title')).not.toBeNull(),
      { timeout: 5000 },
    )

    await tabButton('账户信息').trigger('click')
    await flushPromises()
    expect(
      (wrapper.get('input[autocomplete="name"]').element as HTMLInputElement).value,
    ).toBe('未保存的草稿')
    wrapper.unmount()
  })
})