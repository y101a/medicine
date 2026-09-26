import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import ProfileView from './ProfileView.vue'
import { useAuthStore } from '../stores/auth'
import { usersApi } from '../api/users'
import { ApiError } from '../api/http'

vi.mock('../api/users', () => ({ usersApi: {
  updateProfile: vi.fn(),
  uploadAvatar: vi.fn(),
  deleteAccount: vi.fn(),
  avatarUrl: vi.fn((version: number) => `/api/v1/users/me/avatar?v=${version}`),
} }))

async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore()
  store.user = {
    id: 'user-a', username: 'tester', realName: '张三', gender: 'private',
    role: 'user', phoneMasked: '138****8000', idCardMasked: '110105********002X',
    phoneVerified: true,
    registeredAt: '2026-09-01T00:00:00Z',
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/profile', component: ProfileView },
      { path: '/login', name: 'login', component: { template: '<p>登录页</p>' } },
    ],
  })
  await router.push('/app/profile')
  await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, {
    attachTo: document.body,
    global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, store }
}

describe('个人资料编辑', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => document.body.replaceChildren())

  it('只提交变更的姓名，保存后同步用户资料', async () => {
    const { wrapper, store } = await setup()
    expect(wrapper.text()).toContain('138****8000')
    vi.mocked(usersApi.updateProfile).mockResolvedValue({ ...store.user!, realName: '李明' })
    await wrapper.get('input[autocomplete="name"]').setValue('李明')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(usersApi.updateProfile).toHaveBeenCalledWith({ realName: '李明' })
    expect(store.user?.realName).toBe('李明')
    expect(wrapper.text()).toContain('资料已与账户同步')
    wrapper.unmount()
  })

  it('保存失败保留输入，不改动已保存的资料', async () => {
    const { wrapper, store } = await setup()
    vi.mocked(usersApi.updateProfile).mockRejectedValue(new ApiError('连接失败', 'NETWORK_ERROR'))
    await wrapper.get('input[autocomplete="name"]').setValue('李明')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect((wrapper.get('input[autocomplete="name"]').element as HTMLInputElement).value).toBe('李明')
    expect(store.user?.realName).toBe('张三')
    expect(wrapper.text()).toContain('连接失败')
    wrapper.unmount()
  })

  it('非法姓名不提交请求', async () => {
    const { wrapper } = await setup()
    await wrapper.get('input[autocomplete="name"]').setValue('张')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(usersApi.updateProfile).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('姓名长度应为')
    wrapper.unmount()
  })

  it('选择有效图片后上传头像并刷新显示地址', async () => {
    const { wrapper, store } = await setup()
    vi.mocked(usersApi.uploadAvatar).mockResolvedValue({ avatarUrl: '/api/v1/users/me/avatar' })
    const before = store.avatarUrl
    const input = wrapper.get('input[type="file"]')
    const file = new File(['avatar'], 'avatar.png', { type: 'image/png' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(usersApi.uploadAvatar).toHaveBeenCalledWith(file)
    expect(store.avatarUrl).not.toBe(before)
    wrapper.unmount()
  })

  it('超过 3 MB 或格式不支持的头像不会上传', async () => {
    const { wrapper } = await setup()
    const input = wrapper.get('input[type="file"]')
    const file = new File([new Uint8Array(3 * 1024 * 1024 + 1)], 'large.png', {
      type: 'image/png',
    })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    expect(usersApi.uploadAvatar).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('不能超过 3 MB')
    wrapper.unmount()
  })
})

describe('删除账号', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => document.body.replaceChildren())

  function confirmPassword(password: string) {
    return vi.spyOn(ElMessageBox, 'prompt').mockResolvedValueOnce(
      { value: password, action: 'confirm' } as Awaited<ReturnType<typeof ElMessageBox.prompt>>,
    )
  }

  it('先讲清后果再要密码，成功后清空会话并回到登录页', async () => {
    const { wrapper, store } = await setup()
    vi.mocked(usersApi.deleteAccount).mockResolvedValue(undefined)
    const prompt = confirmPassword('secret123')
    await wrapper.get('.danger-zone button').trigger('click')
    await flushPromises()
    expect(prompt).toHaveBeenCalled()
    expect(String(prompt.mock.calls[0][0])).toContain('永久删除')
    expect(usersApi.deleteAccount).toHaveBeenCalledWith('secret123')
    expect(store.isAuthenticated).toBe(false)
    wrapper.unmount()
  })

  it('密码不正确时保留会话并显示服务端文案', async () => {
    const { wrapper, store } = await setup()
    vi.mocked(usersApi.deleteAccount).mockRejectedValue(
      new ApiError('当前密码不正确', 'ACCOUNT_PASSWORD_INVALID', 422),
    )
    confirmPassword('wrong123')
    await wrapper.get('.danger-zone button').trigger('click')
    await flushPromises()
    expect(store.isAuthenticated, '密码错误不能把本地会话清掉').toBe(true)
    expect(wrapper.text()).toContain('当前密码不正确')
    wrapper.unmount()
  })

  it('取消输入密码则不调用删除接口', async () => {
    const { wrapper, store } = await setup()
    vi.spyOn(ElMessageBox, 'prompt').mockRejectedValueOnce('cancel')
    await wrapper.get('.danger-zone button').trigger('click')
    await flushPromises()
    expect(usersApi.deleteAccount).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(true)
    wrapper.unmount()
  })
})
