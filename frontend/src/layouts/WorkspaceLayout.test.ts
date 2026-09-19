import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import WorkspaceLayout from './WorkspaceLayout.vue'
import { useAuthStore } from '../stores/auth'
import { useHealthRecordsStore } from '../stores/healthRecords'
import { healthRecordsApi } from '../api/healthRecords'
import { consultationsApi } from '../api/consultations'
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
vi.mock('../api/consultations', () => ({
  consultationsApi: {
    create: vi.fn(),
    send: vi.fn(),
    stream: vi.fn(),
    get: vi.fn(),
    messages: vi.fn(),
    list: vi.fn(),
    remove: vi.fn(),
  },
}))

const firstNotice = { collectionEnabled: true, noticeSeen: false, recordCount: 0 }

const record: HealthRecord = {
  id: 'r1',
  category: 'symptom',
  categoryLabel: '近期症状',
  content: '夜间失眠',
  source: 'conversation',
  recordedAt: '2026-09-16T10:00:00Z',
  updatedAt: '2026-09-16T10:00:00Z',
}

async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 'u1',
    username: 'tester',
    realName: '测试',
    gender: 'private',
    role: 'user',
    registeredAt: '2026-09-06',
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app', name: 'home', component: { template: '<p>home</p>' } },
      { path: '/app/chat', name: 'chat', component: { template: '<p>chat</p>' } },
      { path: '/app/history', name: 'history', component: { template: '<p>history</p>' } },
      { path: '/app/settings', name: 'settings', component: { template: '<p>settings</p>' } },
    ],
  })
  await router.push('/app')
  const wrapper = mount(WorkspaceLayout, {
    attachTo: document.body,
    global: { plugins: [pinia, router, ElementPlus] },
  })
  // 登录后检查通知是异步的，弹窗还要经过一次渲染与 Teleport。
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  document.body.innerHTML = ''
  vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...firstNotice })
  vi.mocked(healthRecordsApi.updateSettings).mockResolvedValue({ ...firstNotice, noticeSeen: true })
  vi.mocked(healthRecordsApi.list).mockResolvedValue([])
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [], hasMore: false })
})

describe('工作区布局与健康记录接入', () => {
  it('登录成功后自动检查并弹出首次采集通知', async () => {
    const { wrapper } = await setup()

    expect(healthRecordsApi.settings).toHaveBeenCalledTimes(1)
    expect(useHealthRecordsStore().noticeVisible).toBe(true)
    expect(document.querySelector('.health-notice__skip')).not.toBeNull()
    expect(document.querySelector('.health-notice__disable')).not.toBeNull()
    wrapper.unmount()
  })

  it('已经看过通知的账号不再弹出', async () => {
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...firstNotice, noticeSeen: true })
    const { wrapper } = await setup()

    expect(useHealthRecordsStore().noticeVisible).toBe(false)
    expect(document.querySelector('.health-notice__skip')).toBeNull()
    wrapper.unmount()
  })

  it('导航底部提供设置入口，且不再单列健康记录与个人中心', async () => {
    const { wrapper } = await setup()

    const link = wrapper.find('a[href="/app/settings"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('设置')
    // 这两项已并入设置页分栏；断言它们确实从导航里消失，避免以为入口还留着。
    expect(wrapper.find('a[href="/app/health-records"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/app/profile"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('离开工作区时清理状态，避免下一个账号看到上一个用户的记录', async () => {
    const { wrapper } = await setup()
    const store = useHealthRecordsStore()
    store.records = [record]
    expect(store.noticeVisible).toBe(true)

    wrapper.unmount()

    expect(store.records).toEqual([])
    expect(store.settings).toBeNull()
    expect(store.noticeVisible).toBe(false)
  })
})