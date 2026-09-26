import http, { ApiError, getApiErrorMessage } from './http'
import { mockAuthApi } from './mockAuth'
import type {
  AuthResult,
  AuthUser,
  LoginRequest,
  PasswordResetRequest,
  PhoneVerificationChallenge,
  PhoneVerificationCodeRequest,
  PhoneVerificationGrant,
  PhoneVerificationVerifyRequest,
  RegisterRequest,
} from '../types/auth'

export const useMockAuth = import.meta.env.VITE_USE_MOCK_API === 'true'
  || (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_API !== 'false')

export const authApi = {
  async register(payload: RegisterRequest) {
    if (useMockAuth) return mockAuthApi.register(payload)
    return (await http.post<AuthResult>('/auth/register', payload)).data
  },

  async login(payload: LoginRequest) {
    if (useMockAuth) return mockAuthApi.login(payload)
    return (await http.post<AuthResult>('/auth/login', payload)).data
  },

  async refresh() {
    if (useMockAuth) return mockAuthApi.refresh()
    return (await http.post<AuthResult>('/auth/refresh')).data
  },

  async logout() {
    if (useMockAuth) return mockAuthApi.logout()
    await http.post('/auth/logout')
  },

  async getCurrentUser() {
    if (useMockAuth) return mockAuthApi.getCurrentUser()
    return (await http.get<AuthUser>('/users/me')).data
  },

  /** 5.1 发送注册或找回密码验证码（202）。找回时后端对「不存在/未验证」的手机号也返回同形状。 */
  async requestPhoneVerificationCode(payload: PhoneVerificationCodeRequest) {
    if (useMockAuth) return mockAuthApi.requestPhoneVerificationCode(payload)
    return (await http.post<PhoneVerificationChallenge>('/auth/phone-verifications/code', payload)).data
  },

  /** 5.2 校验验证码，换一次性令牌（200）。令牌不代表已登录。 */
  async verifyPhoneVerificationCode(payload: PhoneVerificationVerifyRequest) {
    if (useMockAuth) return mockAuthApi.verifyPhoneVerificationCode(payload)
    return (await http.post<PhoneVerificationGrant>('/auth/phone-verifications/verify', payload)).data
  },

  /** 5.4 重置密码：成功是 204，没有响应体。 */
  async resetPassword(payload: PasswordResetRequest) {
    if (useMockAuth) return mockAuthApi.resetPassword(payload)
    await http.post('/auth/password-reset', payload)
  },

  /**
   * 5.5 已有用户补验证：手机号必须由后端从加密资料解密取得，前端**不传**手机号。
   *
   * 放在 `authApi` 而不是 `usersApi`，是因为 `http` 层把「登录态」相关接口集中在这里
   * （`getCurrentUser` 本身就是 `/users/me`）；路径本身仍是第 5 节冻结的那两条。
   */
  async requestCurrentPhoneCode() {
    if (useMockAuth) return mockAuthApi.requestCurrentPhoneCode()
    return (await http.post<PhoneVerificationChallenge>('/users/me/phone-verification/code')).data
  },

  async confirmCurrentPhone(payload: PhoneVerificationVerifyRequest) {
    if (useMockAuth) return mockAuthApi.confirmCurrentPhone(payload)
    await http.post('/users/me/phone-verification/confirm', payload)
  },
}

/**
 * 6 节错误码 → 中文文案。
 *
 * 本地表优先于服务端文案：这几种情况界面上的说法必须可控（尤其找回密码不得泄露
 * 「手机号是否存在/是否已验证」）。表里没有的码才退回服务端给的可读中文。
 */
const PHONE_VERIFICATION_MESSAGES: Record<string, string> = {
  SMS_PHONE_INVALID: '请输入有效的中国大陆手机号',
  SMS_CHALLENGE_INVALID: '验证码已失效，请重新获取',
  SMS_CODE_INVALID: '验证码不正确，请检查后重试',
  SMS_CODE_EXPIRED: '验证码已过期，请重新获取',
  SMS_ATTEMPTS_EXCEEDED: '验证码错误次数过多，请重新获取',
  SMS_RATE_LIMITED: '发送过于频繁，请稍后再试',
  PHONE_VERIFICATION_REQUIRED: '请先完成手机号验证',
  PHONE_VERIFICATION_TOKEN_INVALID: '手机号验证已失效，请重新验证',
  SMS_PROVIDER_NOT_CONFIGURED: '短信服务未配置，请联系管理员',
  SMS_PROVIDER_FAILED: '短信发送失败，请稍后再试',
  SMS_PROVIDER_TIMEOUT: '短信发送超时，请稍后再试',
}

/**
 * 找回密码「发送阶段」对外的统一说法（6 节）。
 *
 * 不论接口快慢、成功或「这个手机号不存在」，界面只说这一句；据此无法判断账户是否存在。
 */
export const PASSWORD_RESET_SENT_MESSAGE = '如果该手机号已绑定并完成验证，验证码将发送到该手机。'

function retryAfterSeconds(error: ApiError): number | undefined {
  const details = error.details as { retryAfterSeconds?: unknown } | undefined
  const value = Number(details?.retryAfterSeconds)
  return Number.isFinite(value) && value > 0 ? Math.ceil(value) : undefined
}

/**
 * 取服务端给的「多久之后可以重发」。
 *
 * 调用方拿它直接把按钮切到倒计时，用户不用自己猜什么时候能再点（8 节的限流值只有后端知道）。
 */
export function getRetryAfterSeconds(error: unknown): number | undefined {
  if (!(error instanceof ApiError)) return undefined
  if (error.code !== 'SMS_RATE_LIMITED') return undefined
  return retryAfterSeconds(error)
}

/** 把验证码相关的失败翻成给用户看的中文；限流会带上服务端给的重试秒数。 */
export function getPhoneVerificationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '操作失败，请稍后重试'

  if (error.code === 'SMS_RATE_LIMITED') {
    const seconds = retryAfterSeconds(error)
    if (seconds !== undefined) return `发送过于频繁，请 ${seconds} 秒后重试`
  }

  return PHONE_VERIFICATION_MESSAGES[error.code] ?? getApiErrorMessage(error)
}