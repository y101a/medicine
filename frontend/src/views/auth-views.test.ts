import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import LoginView from './LoginView.vue'
import RegisterView from './RegisterView.vue'
import ForgotPasswordView from './ForgotPasswordView.vue'
import SettingsView from './SettingsView.vue'
import { useAuthStore } from '../stores/auth'

/**
 * 只替换 `authApi`，其余（含 `getPhoneVerificationErrorMessage`、`PASSWORD_RESET_SENT_MESSAGE`）
 * 保留真实实现：这几条是纯映射逻辑，替身会让「错误码翻译成什么中文」这件事失去验证。
 */
vi.mock('../api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/auth')>()
  return {
    ...actual,
    authApi: {
      register: vi.fn(),
      login: vi.fn(),
      refresh: vi.fn(),
      logout: vi.fn(),
      getCurrentUser: vi.fn(),
      requestPhoneVerificationCode: vi.fn(),
      verifyPhoneVerificationCode: vi.fn(),
      resetPassword: vi.fn(),
      requestCurrentPhoneCode: vi.fn(),
      confirmCurrentPhone: vi.fn(),
    },
  }
})

import { PASSWORD_RESET_SENT_MESSAGE, authApi, getPhoneVerificationErrorMessage } from '../api/auth'
import { ApiError } from '../api/http'
import { mockAuthApi } from '../api/mockAuth'

const PHONE = '13800138000'
const OTHER_PHONE = '13900139000'
/** 校验位正确的示例身份证（110105 / 1949-12-31）。 */
const ID_CARD = '11010519491231002X'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/register', name: 'register', component: RegisterView },
      { path: '/forgot-password', name: 'forgot-password', component: ForgotPasswordView },
      { path: '/app', component: { template: '<div>home</div>' } },
      { path: '/app/settings', name: 'settings', component: SettingsView },
    ],
  })
}

async function mountAt(path: string, component: unknown, options: Record<string, unknown> = {}) {
  const router = createTestRouter()
  await router.push(path)
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(component as never, {
    global: { plugins: [pinia, router, ElementPlus], ...(options.global as object ?? {}) },
  })
  return { wrapper, router, pinia }
}

function userFixture(phoneVerified: boolean) {
  return {
    id: 'u1',
    username: 'tester',
    realName: '张三',
    gender: 'private' as const,
    role: 'user' as const,
    phoneMasked: '138****8000',
    phoneVerified,
    registeredAt: '2026-09-01T00:00:00Z',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('auth views', () => {
  it('登录页展示必要的认证入口', async () => {
    const { wrapper } = await mountAt('/login', LoginView)

    expect(wrapper.text()).toContain('病理诊断科普助手')
    expect(wrapper.text()).toContain('用户名')
    expect(wrapper.text()).toContain('密码')
    expect(wrapper.text()).toContain('注册账号')
  })

  it('注册页展示全部已确认字段', async () => {
    const { wrapper } = await mountAt('/register', RegisterView)

    for (const label of ['用户名', '姓名', '手机号', '短信验证码', '性别', '身份证号码', '确认密码']) {
      expect(wrapper.text()).toContain(label)
    }
  })

  it('登录页「忘记密码？」跳到找回页，不再显示占位提示', async () => {
    const infoSpy = vi.spyOn(ElMessage, 'info')
    const { wrapper, router } = await mountAt('/login', LoginView)

    const forgotButton = wrapper.findAll('button.text-button')
      .find(button => button.text().includes('忘记密码'))
    expect(forgotButton, '登录页应有「忘记密码？」入口').toBeTruthy()

    await forgotButton!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/forgot-password')
    expect(infoSpy).not.toHaveBeenCalled()
  })
})

describe('注册页手机号验证', () => {
  it('没有通过验证时不能提交注册，接口也不会被调用', async () => {
    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    const submit = wrapper.find('.register-button')
    expect(submit.classes()).toContain('is-disabled')

    await submit.trigger('click')
    expect(authApi.register).not.toHaveBeenCalled()
  })

  it('获取验证码：按钮先禁用、发出请求后进入服务端给的倒计时，重复点击不再发请求', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    const { wrapper } = await mountAt('/register', RegisterView)

    const sendButton = wrapper.find('.send-code-button')
    expect(sendButton.classes(), '手机号还没填时不能点').toContain('is-disabled')

    await wrapper.find('.phone-input input').setValue(PHONE)
    expect(wrapper.find('.send-code-button').classes()).not.toContain('is-disabled')

    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => {
      expect(authApi.requestPhoneVerificationCode).toHaveBeenCalledTimes(1)
    })
    expect(authApi.requestPhoneVerificationCode).toHaveBeenCalledWith({
      phone: PHONE,
      purpose: 'registration',
    })
    expect(wrapper.find('.send-code-button').text()).toContain('60 秒后可重发')

    await wrapper.find('.send-code-button').trigger('click')
    await Promise.resolve()
    expect(authApi.requestPhoneVerificationCode, '倒计时里重复点击不该再发短信').toHaveBeenCalledTimes(1)
  })

  it('验证码正确后出现已验证提示，提交按钮才可用；提交会带上一次性令牌', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockResolvedValue({
      verificationToken: 'grant-1',
      expiresInSeconds: 600,
    })
    vi.mocked(authApi.register).mockResolvedValue({ user: userFixture(true) })

    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => {
      expect(authApi.requestPhoneVerificationCode).toHaveBeenCalled()
    })

    await wrapper.find('.code-input input').setValue('482731')
    await wrapper.find('.verify-code-button').trigger('click')
    await vi.waitFor(() => {
      expect(authApi.verifyPhoneVerificationCode).toHaveBeenCalledWith({
        challengeId: 'c-1',
        code: '482731',
      })
    })

    expect(wrapper.find('.code-hint--ok').exists()).toBe(true)
    expect(wrapper.find('.register-button').classes()).not.toContain('is-disabled')
  })

  it('修改手机号会立刻清掉已验证状态，提交按钮重新变灰', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockResolvedValue({
      verificationToken: 'grant-1',
      expiresInSeconds: 600,
    })
    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => expect(authApi.requestPhoneVerificationCode).toHaveBeenCalled())
    await wrapper.find('.code-input input').setValue('482731')
    await wrapper.find('.verify-code-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.code-hint--ok').exists()).toBe(true))

    await wrapper.find('.phone-input input').setValue(OTHER_PHONE)

    expect(wrapper.find('.code-hint--ok').exists(), '改号后不能继续显示已验证').toBe(false)
    expect(wrapper.find('.register-button').classes()).toContain('is-disabled')
    expect(wrapper.find('.code-input input').attributes('disabled')).toBeDefined()
  })

  it('验证码错误显示中文文案且不授予验证状态', async () => {
    const errorSpy = vi.spyOn(ElMessage, 'error')
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockRejectedValue(
      new ApiError('提交的信息校验未通过', 'SMS_CODE_INVALID', 422),
    )
    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => expect(authApi.requestPhoneVerificationCode).toHaveBeenCalled())
    await wrapper.find('.code-input input').setValue('000000')
    await wrapper.find('.verify-code-button').trigger('click')

    await vi.waitFor(() => expect(errorSpy).toHaveBeenCalledWith('验证码不正确，请检查后重试'))
    expect(wrapper.find('.code-hint--ok').exists()).toBe(false)
    expect(wrapper.find('.register-button').classes()).toContain('is-disabled')
  })

  it('验证码过期后退回「重新获取」，输入框重新禁用', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockRejectedValue(
      new ApiError('提交的信息校验未通过', 'SMS_CODE_EXPIRED', 422),
    )
    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => expect(authApi.requestPhoneVerificationCode).toHaveBeenCalled())
    await wrapper.find('.code-input input').setValue('482731')
    await wrapper.find('.verify-code-button').trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.find('.code-input input').attributes('disabled')).toBeDefined()
    })
    expect(wrapper.find('.code-hint').exists()).toBe(false)
  })

  it('发送被限流时用服务端给的剩余秒数提示并开始倒计时', async () => {
    const errorSpy = vi.spyOn(ElMessage, 'error')
    vi.mocked(authApi.requestPhoneVerificationCode).mockRejectedValue(
      new ApiError('请求过于频繁，请稍后再试', 'SMS_RATE_LIMITED', 429, { retryAfterSeconds: 42 }),
    )
    const { wrapper } = await mountAt('/register', RegisterView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')

    await vi.waitFor(() => expect(errorSpy).toHaveBeenCalledWith('发送过于频繁，请 42 秒后重试'))
    expect(wrapper.find('.send-code-button').text()).toContain('42 秒后可重发')
  })

  it('错误码到中文的映射：覆盖 6 节里前端会遇到的码', () => {
    expect(getPhoneVerificationErrorMessage(new ApiError('x', 'SMS_CODE_INVALID')))
      .toBe('验证码不正确，请检查后重试')
    expect(getPhoneVerificationErrorMessage(new ApiError('x', 'SMS_ATTEMPTS_EXCEEDED')))
      .toBe('验证码错误次数过多，请重新获取')
    expect(getPhoneVerificationErrorMessage(new ApiError('x', 'PHONE_VERIFICATION_REQUIRED')))
      .toBe('请先完成手机号验证')
    expect(getPhoneVerificationErrorMessage(new ApiError('x', 'PHONE_VERIFICATION_TOKEN_INVALID')))
      .toBe('手机号验证已失效，请重新验证')
    // 表里没有的码退回服务端给的可读中文，而不是吞掉它。
    expect(getPhoneVerificationErrorMessage(new ApiError('服务端专门说明的文案', 'SOME_NEW_CODE')))
      .toBe('服务端专门说明的文案')
  })
})

describe('忘记密码页', () => {
  it('发送后只显示统一文案，页面不出现「不存在 / 未验证」这类账户枚举线索', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    const { wrapper } = await mountAt('/forgot-password', ForgotPasswordView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.find('.reset-notice').text()).toBe(PASSWORD_RESET_SENT_MESSAGE)
    })
    expect(authApi.requestPhoneVerificationCode).toHaveBeenCalledWith({
      phone: PHONE,
      purpose: 'password_reset',
    })

    const text = wrapper.text()
    for (const leak of ['不存在', '未注册', '尚未验证', '未验证']) {
      expect(text, `不得出现「${leak}」`).not.toContain(leak)
    }
  })

  it('三步走完：验证码换令牌 → 重置密码 → 回登录页并带上提示原因', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockResolvedValue({
      verificationToken: 'grant-1',
      expiresInSeconds: 600,
    })
    vi.mocked(authApi.resetPassword).mockResolvedValue(undefined)

    const { wrapper, router } = await mountAt('/forgot-password', ForgotPasswordView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.code-input').exists()).toBe(true))

    await wrapper.find('.code-input input').setValue('482731')
    await wrapper.find('.verify-code-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.password-input').exists()).toBe(true))

    await wrapper.find('.password-input input').setValue('new-password-1')
    await wrapper.find('.confirm-password-input input').setValue('new-password-1')
    // 直接用表单提交，而不是点按钮：jsdom 里点 `native-type="submit"` 的按钮不会走表单提交，
    // 真实点击由 e2e 覆盖。
    await wrapper.find('form.forgot-form').trigger('submit')

    await vi.waitFor(() => {
      expect(authApi.resetPassword).toHaveBeenCalledWith({
        phone: PHONE,
        verificationToken: 'grant-1',
        newPassword: 'new-password-1',
      })
    })
    await vi.waitFor(() => {
      expect(router.currentRoute.value.name).toBe('login')
    })
    expect(router.currentRoute.value.query.reason).toBe('password-reset')
  })

  it('令牌失效时退回第一步，不让用户对着死掉的输入框反复试', async () => {
    vi.mocked(authApi.requestPhoneVerificationCode).mockResolvedValue({
      challengeId: 'c-1',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.verifyPhoneVerificationCode).mockResolvedValue({
      verificationToken: 'grant-1',
      expiresInSeconds: 600,
    })
    vi.mocked(authApi.resetPassword).mockRejectedValue(
      new ApiError('提交的信息校验未通过', 'PHONE_VERIFICATION_TOKEN_INVALID', 422),
    )

    const { wrapper } = await mountAt('/forgot-password', ForgotPasswordView)

    await wrapper.find('.phone-input input').setValue(PHONE)
    await wrapper.find('.send-code-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.code-input').exists()).toBe(true))
    await wrapper.find('.code-input input').setValue('482731')
    await wrapper.find('.verify-code-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.password-input').exists()).toBe(true))

    await wrapper.find('.password-input input').setValue('new-password-1')
    await wrapper.find('.confirm-password-input input').setValue('new-password-1')
    await wrapper.find('form.forgot-form').trigger('submit')

    await vi.waitFor(() => expect(wrapper.find('.phone-input').exists()).toBe(true))
    expect(wrapper.find('.reset-notice').exists()).toBe(false)
  })
})

describe('设置页手机号补验证', () => {
  it('phoneVerified=false 显示补验证入口，true 时隐藏；入口只显示脱敏号码', async () => {
    const { wrapper, pinia } = await mountAt('/app/settings', SettingsView, {
      global: { stubs: { ProfileView: true } },
    })
    const store = useAuthStore(pinia)

    store.user = userFixture(false)
    await flushPromises()
    expect(wrapper.find('.phone-verification').exists()).toBe(true)
    expect(wrapper.text()).toContain('验证当前手机号')
    expect(wrapper.text()).toContain('138****8000')
    expect(wrapper.text(), '不得展示完整手机号').not.toContain('13800138000')

    store.user = userFixture(true)
    await flushPromises()
    expect(wrapper.find('.phone-verification').exists()).toBe(false)
  })

  it('补验证成功后入口立即消失（本地状态即真值，不需要再拉一次 /users/me）', async () => {
    vi.mocked(authApi.requestCurrentPhoneCode).mockResolvedValue({
      challengeId: 'c-9',
      expiresInSeconds: 300,
      resendAfterSeconds: 60,
    })
    vi.mocked(authApi.confirmCurrentPhone).mockResolvedValue(undefined)

    const { wrapper, pinia } = await mountAt('/app/settings', SettingsView, {
      global: { stubs: { ProfileView: true } },
    })
    const store = useAuthStore(pinia)
    store.user = userFixture(false)
    await flushPromises()

    await wrapper.find('.phone-verification__request').trigger('click')
    await vi.waitFor(() => expect(authApi.requestCurrentPhoneCode).toHaveBeenCalledTimes(1))
    // 等状态落地再输验证码：否则按钮还是「未获取验证码」的禁用态，点了不会有反应。
    await vi.waitFor(() => expect(wrapper.find('.phone-verification__hint').exists()).toBe(true))

    await wrapper.find('.phone-verification__code input').setValue('482731')
    await flushPromises()
    await wrapper.find('.phone-verification__confirm').trigger('click')

    await vi.waitFor(() => {
      expect(authApi.confirmCurrentPhone).toHaveBeenCalledWith({ challengeId: 'c-9', code: '482731' })
    })
    await vi.waitFor(() => {
      expect(wrapper.find('.phone-verification').exists()).toBe(false)
    })
    expect(store.user?.phoneVerified).toBe(true)
  })
})

describe('敏感值不落浏览器存储', () => {
  it('mock 的验证码与一次性令牌只在内存里，localStorage / sessionStorage 都不出现', async () => {
    localStorage.clear()
    sessionStorage.clear()

    const challenge = await mockAuthApi.requestPhoneVerificationCode({
      phone: PHONE,
      purpose: 'registration',
    })
    const grant = await mockAuthApi.verifyPhoneVerificationCode({
      challengeId: challenge.challengeId,
      code: '123456',
    })
    await mockAuthApi.register({
      username: 'tester',
      realName: '张三',
      phone: PHONE,
      idCard: ID_CARD,
      gender: 'private',
      password: 'secret-password',
      phoneVerificationToken: grant.verificationToken,
    })

    const dump = `${JSON.stringify(localStorage)}|${JSON.stringify(sessionStorage)}`
    for (const secret of ['123456', grant.verificationToken, 'secret-password', PHONE]) {
      expect(dump, `存储里不得出现 ${secret}`).not.toContain(secret)
    }
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})