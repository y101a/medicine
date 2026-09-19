import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import SettingsView from './SettingsView.vue'
import { useAuthStore } from '../stores/auth'
import { healthRecordsApi } from '../api/healthRecords'
import { modelCredentialsApi } from '../api/modelCredentials'
import { ApiError } from '../api/http'

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
vi.mock('../api/modelCredentials', () => {
  const api = { list: vi.fn(), save: vi.fn(), remove: vi.fn() }
  return { modelCredentialsApi: api, default: api }
})

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

describe('设置页 · 模型与密钥', () => {
  const summary = {
    provider: 'deepseek',
    maskedKey: 'sk-…4f2a',
    updatedAt: '2026-09-19T12:00:00Z',
    lastVerifiedAt: '2026-09-19T12:00:00Z',
  }

  function tabButton(wrapper: VueWrapper, label: string) {
    const found = wrapper.findAll('[role="tab"]').find(item => item.text().includes(label))
    expect(found, `应存在「${label}」分栏按钮`).toBeTruthy()
    return found!
  }

  function providerRow(wrapper: VueWrapper, name: string) {
    const found = wrapper
      .findAll('.credentials__item')
      .find(item => item.text().includes(name))
    expect(found, `应存在「${name}」服务商条目`).toBeTruthy()
    return found!
  }

  function buttonIn(row: ReturnType<typeof providerRow>, label: string) {
    const found = row.findAll('button').find(item => item.text() === label)
    expect(found, `应存在「${label}」按钮`).toBeTruthy()
    return found!
  }

  beforeEach(() => {
    // vi.clearAllMocks 只清调用记录、不清实现，所以这里显式重设默认实现，
    // 否则上一条用例的 mockRejectedValue 会漏到后面（同文件内的用例共用这些 mock）。
    vi.restoreAllMocks()
    vi.clearAllMocks()
    document.body.replaceChildren()
    vi.mocked(modelCredentialsApi.list).mockResolvedValue([])
    vi.mocked(modelCredentialsApi.save).mockResolvedValue({ ...summary })
    vi.mocked(modelCredentialsApi.remove).mockResolvedValue(undefined)
  })

  it('默认分栏不请求凭据接口，首次打开该分栏才请求一次', async () => {
    const wrapper = await setup()
    expect(modelCredentialsApi.list).not.toHaveBeenCalled()

    await tabButton(wrapper, '模型与密钥').trigger('click')
    await flushPromises()
    expect(modelCredentialsApi.list).toHaveBeenCalledTimes(1)

    // 分栏保持挂载：切走再切回不该重复请求，也不该丢掉输入框。
    await tabButton(wrapper, '账户信息').trigger('click')
    await tabButton(wrapper, '模型与密钥').trigger('click')
    await flushPromises()
    expect(modelCredentialsApi.list).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('列出四家服务商，并披露数据流向与脱敏限度', async () => {
    const wrapper = await setup('?tab=credentials')
    await flushPromises()

    for (const name of ['DeepSeek', '阿里云百炼', 'Kimi', '智谱 AI']) {
      expect(providerRow(wrapper, name).text()).toContain('未配置')
    }

    const notice = wrapper.get('.credentials__notice').text()
    expect(notice).toContain('会发送到该服务商')
    expect(notice).toContain('不等于健康文本已经匿名化')
    expect(notice).toContain('不作诊断、不替代医生')
    wrapper.unmount()
  })

  it('已配置的服务商只显示掩码与最近验证时间，界面上没有明文输入框', async () => {
    vi.mocked(modelCredentialsApi.list).mockResolvedValue([{ ...summary }])
    const wrapper = await setup('?tab=credentials')
    await flushPromises()

    const row = providerRow(wrapper, 'DeepSeek')
    expect(row.text()).toContain('已配置 · sk-…4f2a')
    expect(row.text()).toContain('最近验证：')
    expect(row.find('input').exists()).toBe(false)
    wrapper.unmount()
  })

  it('Key 短于 8 位时本地拦下，不发请求', async () => {
    const wrapper = await setup('?tab=credentials')
    await flushPromises()
    const row = providerRow(wrapper, 'DeepSeek')

    await buttonIn(row, '填入 API Key').trigger('click')
    await row.get('input').setValue('sk-1')
    await buttonIn(row, '验证并保存').trigger('click')
    await flushPromises()

    expect(modelCredentialsApi.save).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('保存成功后显示掩码，并清掉输入框里的明文', async () => {
    const wrapper = await setup('?tab=credentials')
    await flushPromises()
    const row = providerRow(wrapper, 'DeepSeek')

    await buttonIn(row, '填入 API Key').trigger('click')
    await row.get('input').setValue('sk-abcdefghijk')
    await buttonIn(row, '验证并保存').trigger('click')
    await flushPromises()

    expect(modelCredentialsApi.save).toHaveBeenCalledWith('deepseek', 'sk-abcdefghijk')
    expect(providerRow(wrapper, 'DeepSeek').text()).toContain('已配置 · sk-…4f2a')
    expect(wrapper.find('.credentials__editor').exists()).toBe(false)
    wrapper.unmount()
  })

  it('服务商拒绝时显示服务端文案，且不会变成已配置', async () => {
    vi.mocked(modelCredentialsApi.save).mockRejectedValue(
      new ApiError('API Key 无效、无权限或当前不可用', 'MODEL_CREDENTIAL_INVALID', 422),
    )
    const wrapper = await setup('?tab=credentials')
    await flushPromises()
    const row = providerRow(wrapper, 'DeepSeek')

    await buttonIn(row, '填入 API Key').trigger('click')
    await row.get('input').setValue('sk-bad-abcdefgh')
    await buttonIn(row, '验证并保存').trigger('click')
    await vi.waitFor(
      () => expect(document.body.textContent).toContain('API Key 无效、无权限或当前不可用'),
      { timeout: 5000 },
    )

    expect(providerRow(wrapper, 'DeepSeek').text()).toContain('未配置')
    wrapper.unmount()
  })

  it('验证过频（429）时补上「10 分钟 5 次」这句可操作提示', async () => {
    vi.mocked(modelCredentialsApi.save).mockRejectedValue(
      new ApiError('模型密钥验证过于频繁，请稍后再试', 'MODEL_CREDENTIAL_RATE_LIMITED', 429),
    )
    const wrapper = await setup('?tab=credentials')
    await flushPromises()
    const row = providerRow(wrapper, 'DeepSeek')

    await buttonIn(row, '填入 API Key').trigger('click')
    await row.get('input').setValue('sk-abcdefghijk')
    await buttonIn(row, '验证并保存').trigger('click')
    await vi.waitFor(
      () => expect(document.body.textContent).toContain('10 分钟内最多验证 5 次'),
      { timeout: 5000 },
    )
    wrapper.unmount()
  })

  it('删除需确认；确认后调用删除接口并回到未配置', async () => {
    vi.mocked(modelCredentialsApi.list).mockResolvedValue([{ ...summary }])
    const confirm = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValueOnce('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
    const wrapper = await setup('?tab=credentials')
    await flushPromises()

    await buttonIn(providerRow(wrapper, 'DeepSeek'), '删除').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(modelCredentialsApi.remove).toHaveBeenCalledWith('deepseek')
    expect(providerRow(wrapper, 'DeepSeek').text()).toContain('未配置')
    wrapper.unmount()
  })

  it('取消删除时不调用删除接口，状态保持已配置', async () => {
    vi.mocked(modelCredentialsApi.list).mockResolvedValue([{ ...summary }])
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    const wrapper = await setup('?tab=credentials')
    await flushPromises()

    await buttonIn(providerRow(wrapper, 'DeepSeek'), '删除').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(modelCredentialsApi.remove).not.toHaveBeenCalled()
    expect(providerRow(wrapper, 'DeepSeek').text()).toContain('已配置')
    wrapper.unmount()
  })

  it('切到别的分栏再回来，还没保存的 Key 草稿还在', async () => {
    const wrapper = await setup('?tab=credentials')
    await flushPromises()
    const row = providerRow(wrapper, 'DeepSeek')

    await buttonIn(row, '填入 API Key').trigger('click')
    await row.get('input').setValue('sk-还没保存')
    await tabButton(wrapper, '账户信息').trigger('click')
    await flushPromises()
    await tabButton(wrapper, '模型与密钥').trigger('click')
    await flushPromises()

    const input = wrapper.get('.credentials__item input').element as HTMLInputElement
    expect(input.value).toBe('sk-还没保存')
    wrapper.unmount()
  })
})