import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { healthRecordsApi } from '../api/healthRecords'
import { useHealthRecordsStore } from './healthRecords'
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

const baseSettings = { collectionEnabled: true, noticeSeen: false, recordCount: 0 }

const record: HealthRecord = {
  id: 'r1',
  category: 'symptom',
  categoryLabel: '近期症状',
  content: '夜间失眠',
  source: 'conversation',
  recordedAt: '2026-09-16T10:00:00Z',
  updatedAt: '2026-09-16T10:00:00Z',
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...baseSettings })
  vi.mocked(healthRecordsApi.updateSettings).mockResolvedValue({
    ...baseSettings,
    noticeSeen: true,
  })
  vi.mocked(healthRecordsApi.list).mockResolvedValue([])
})

describe('健康记录 store', () => {
  it('缺少设置时按已确认的默认值处理：默认采集、未通知', async () => {
    const store = useHealthRecordsStore()
    expect(store.collectionEnabled).toBe(true)
    await store.loadSettings()
    expect(store.settings).toEqual(baseSettings)
  })

  it('首次登录自动弹出采集通知', async () => {
    const store = useHealthRecordsStore()
    expect(store.noticeVisible).toBe(false)
    await store.checkFirstNotice()
    expect(store.noticeVisible).toBe(true)
  })

  it('通知已看过之后不再弹出', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...baseSettings, noticeSeen: true })
    await store.checkFirstNotice()
    expect(store.noticeVisible).toBe(false)
  })

  it('已经关闭采集的用户不再被通知打扰', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.settings).mockResolvedValue({
      ...baseSettings,
      collectionEnabled: false,
      noticeSeen: false,
    })
    await store.checkFirstNotice()
    expect(store.noticeVisible).toBe(false)
  })

  it('同一会话只检查一次，读取失败时静默不弹窗', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.settings).mockRejectedValue(new Error('boom'))
    expect(await store.checkFirstNotice()).toBe(false)
    expect(store.noticeVisible).toBe(false)

    vi.mocked(healthRecordsApi.settings).mockResolvedValue({ ...baseSettings })
    expect(await store.checkFirstNotice()).toBe(false)
    expect(healthRecordsApi.settings).toHaveBeenCalledTimes(1)
  })

  it('关闭采集后 collectionEnabled 立即变为 false', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.updateSettings).mockResolvedValue({
      ...baseSettings,
      collectionEnabled: false,
      noticeSeen: true,
    })
    await store.setCollection(false)
    expect(store.collectionEnabled).toBe(false)
    expect(healthRecordsApi.updateSettings).toHaveBeenCalledWith({ collectionEnabled: false })
  })

  it('加载失败时记录错误信息而不是抛异常', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.list).mockRejectedValue(new Error('boom'))
    await store.loadRecords()
    expect(store.records).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBe('发生未知错误，请稍后重试')
  })

  it('列表按接口返回顺序保存在 store 中', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.list).mockResolvedValue([record])
    await store.loadRecords()
    expect(store.records).toEqual([record])
  })

  it('编辑与删除都会重新拉取列表', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.list).mockResolvedValue([record])
    vi.mocked(healthRecordsApi.update).mockResolvedValue(record)
    vi.mocked(healthRecordsApi.remove).mockResolvedValue(undefined)

    await store.editRecord('r1', '最近一周夜间失眠')
    expect(healthRecordsApi.update).toHaveBeenCalledWith('r1', { content: '最近一周夜间失眠' })

    await store.removeRecord('r1')
    expect(healthRecordsApi.remove).toHaveBeenCalledWith('r1')
    expect(healthRecordsApi.list).toHaveBeenCalledTimes(2)
  })

  it('对话增量更新失败时静默忽略，不影响对话', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.extract).mockRejectedValue(new Error('boom'))
    await expect(store.syncFromMessage('c1', 'm1')).resolves.toBeUndefined()
    expect(healthRecordsApi.extract).toHaveBeenCalledWith({
      consultationId: 'c1',
      messageId: 'm1',
    })
  })

  it('退出登录时清理状态，避免下个用户看到上一个用户的记录', async () => {
    const store = useHealthRecordsStore()
    vi.mocked(healthRecordsApi.list).mockResolvedValue([record])
    await store.loadRecords()
    expect(store.records).toHaveLength(1)

    store.reset()
    expect(store.records).toEqual([])
    expect(store.settings).toBeNull()
    expect(store.noticeVisible).toBe(false)
    expect(store.collectionEnabled).toBe(true)
  })
})