import { ApiError } from './http'
import type {
  AuthResult,
  AuthUser,
  LoginRequest,
  PasswordResetRequest,
  PhoneVerificationChallenge,
  PhoneVerificationCodeRequest,
  PhoneVerificationGrant,
  PhoneVerificationPurpose,
  PhoneVerificationVerifyRequest,
  RegisterRequest,
} from '../types/auth'

const MOCK_SESSION_KEY = 'medical-assistant:mock-user'
const MOCK_DELAY_MS = 500

/**
 * 模拟短信的固定验证码。
 *
 * 只服务于「后端还没就绪时前端能自测」这一种情况，和真实链路无关：真实验证码由后端用
 * `secrets` 生成、只在开发终端打印一次，HTTP 响应和浏览器存储都不会出现它。
 */
const MOCK_SMS_CODE = '123456'
const MOCK_CHALLENGE_TTL_SECONDS = 300
const MOCK_RESEND_SECONDS = 60
const MOCK_TOKEN_TTL_SECONDS = 600
const MOCK_MAX_ATTEMPTS = 5
/** mock 登录用户的手机号，故意保持「未验证」：开发环境要能验收设置页的补验证入口。 */
const MOCK_PHONE = '13800138000'

/** 数据库允许三种用途；本期前端只用到前两种，补验证固定是 phone_binding。 */
type MockPurpose = PhoneVerificationPurpose | 'phone_binding'

interface MockChallenge {
  id: string
  phone: string
  purpose: MockPurpose
  code: string
  expiresAt: number
  attempts: number
}

interface MockGrant {
  token: string
  phone: string
  purpose: MockPurpose
  expiresAt: number
  consumed: boolean
}

/**
 * 挑战与一次性令牌只放在内存里。
 *
 * 这是刻意的：6 节要求验证码与 `verificationToken` 不落浏览器存储，mock 也必须守同一条规矩，
 * 否则单测里「存储里没有验证码」的断言会因为 mock 自己写盘而变成假通过。
 */
const challenges = new Map<string, MockChallenge>()
const grants = new Map<string, MockGrant>()

const delay = () => new Promise<void>((resolve) => window.setTimeout(resolve, MOCK_DELAY_MS))
const maskPhone = (phone: string) => `${phone.slice(0, 3)}****${phone.slice(-4)}`
const maskIdCard = (idCard: string) => `${idCard.slice(0, 6)}********${idCard.slice(-4)}`

function saveSafeSession(user: AuthUser) {
  sessionStorage.setItem(MOCK_SESSION_KEY, JSON.stringify(user))
}

function readSafeSession(): AuthUser | null {
  const value = sessionStorage.getItem(MOCK_SESSION_KEY)
  if (!value) return null
  try {
    return JSON.parse(value) as AuthUser
  } catch {
    sessionStorage.removeItem(MOCK_SESSION_KEY)
    return null
  }
}

function isValidPhone(phone: string) {
  return /^1[3-9]\d{9}$/.test(phone)
}

function createChallenge(phone: string, purpose: MockPurpose): PhoneVerificationChallenge {
  const id = `mock-challenge-${Date.now()}-${challenges.size}`
  challenges.set(id, {
    id,
    phone,
    purpose,
    code: MOCK_SMS_CODE,
    expiresAt: Date.now() + MOCK_CHALLENGE_TTL_SECONDS * 1000,
    attempts: 0,
  })
  console.info(`[mock SMS] ${maskPhone(phone)} 验证码 ${MOCK_SMS_CODE}，${MOCK_CHALLENGE_TTL_SECONDS / 60} 分钟内有效`)
  return {
    challengeId: id,
    expiresInSeconds: MOCK_CHALLENGE_TTL_SECONDS,
    resendAfterSeconds: MOCK_RESEND_SECONDS,
  }
}

function takeChallenge(challengeId: string): MockChallenge {
  const challenge = challenges.get(challengeId)
  if (!challenge) throw new ApiError('验证码已失效，请重新获取', 'SMS_CHALLENGE_INVALID', 422)
  if (challenge.expiresAt <= Date.now()) {
    challenges.delete(challengeId)
    throw new ApiError('验证码已过期，请重新获取', 'SMS_CODE_EXPIRED', 422)
  }
  if (challenge.attempts >= MOCK_MAX_ATTEMPTS) {
    challenges.delete(challengeId)
    throw new ApiError('验证码错误次数过多，请重新获取', 'SMS_ATTEMPTS_EXCEEDED', 429)
  }
  return challenge
}

function issueGrant(challenge: MockChallenge): PhoneVerificationGrant {
  const token = `mock-grant-${Date.now()}-${grants.size}`
  grants.set(token, {
    token,
    phone: challenge.phone,
    purpose: challenge.purpose,
    expiresAt: Date.now() + MOCK_TOKEN_TTL_SECONDS * 1000,
    consumed: false,
  })
  return { verificationToken: token, expiresInSeconds: MOCK_TOKEN_TTL_SECONDS }
}

function consumeGrant(token: string, phone: string, purpose: MockPurpose) {
  const grant = grants.get(token)
  if (!grant || grant.consumed || grant.expiresAt <= Date.now()
    || grant.phone !== phone || grant.purpose !== purpose) {
    throw new ApiError('手机号验证已失效，请重新验证', 'PHONE_VERIFICATION_TOKEN_INVALID', 422)
  }
  grant.consumed = true
}

function verifyCode(challengeId: string, code: string): MockChallenge {
  const challenge = takeChallenge(challengeId)
  if (challenge.code !== code) {
    challenge.attempts += 1
    if (challenge.attempts >= MOCK_MAX_ATTEMPTS) {
      challenges.delete(challengeId)
      throw new ApiError('验证码错误次数过多，请重新获取', 'SMS_ATTEMPTS_EXCEEDED', 429)
    }
    throw new ApiError('验证码不正确，请检查后重试', 'SMS_CODE_INVALID', 422)
  }
  challenges.delete(challengeId)
  return challenge
}

export const mockAuthApi = {
  async requestPhoneVerificationCode(
    payload: PhoneVerificationCodeRequest,
  ): Promise<PhoneVerificationChallenge> {
    await delay()
    if (!isValidPhone(payload.phone)) {
      throw new ApiError('请输入有效的中国大陆手机号', 'SMS_PHONE_INVALID', 422)
    }
    // 找回密码一律返回同形状响应，即使「账户不存在」也走这条路径——不制造账户枚举接口。
    return createChallenge(payload.phone, payload.purpose)
  },

  async verifyPhoneVerificationCode(
    payload: PhoneVerificationVerifyRequest,
  ): Promise<PhoneVerificationGrant> {
    await delay()
    const challenge = verifyCode(payload.challengeId, payload.code)
    return issueGrant(challenge)
  },

  async requestCurrentPhoneCode(): Promise<PhoneVerificationChallenge> {
    await delay()
    if (!readSafeSession()) throw new ApiError('当前未登录', 'UNAUTHORIZED', 401)
    return createChallenge(MOCK_PHONE, 'phone_binding')
  },

  async confirmCurrentPhone(payload: PhoneVerificationVerifyRequest): Promise<void> {
    await delay()
    const user = readSafeSession()
    if (!user) throw new ApiError('当前未登录', 'UNAUTHORIZED', 401)
    const challenge = verifyCode(payload.challengeId, payload.code)
    if (challenge.phone !== MOCK_PHONE || challenge.purpose !== 'phone_binding') {
      throw new ApiError('手机号验证已失效，请重新验证', 'PHONE_VERIFICATION_TOKEN_INVALID', 422)
    }
    saveSafeSession({ ...user, phoneMasked: maskPhone(MOCK_PHONE), phoneVerified: true })
  },

  async resetPassword(payload: PasswordResetRequest): Promise<void> {
    await delay()
    if (payload.newPassword.length < 6) {
      throw new ApiError('密码长度应为 6–32 位', 'PASSWORD_INVALID', 422)
    }
    consumeGrant(payload.verificationToken, payload.phone, 'password_reset')
    // 真实后端会撤销全部刷新会话并提升认证版本；mock 里等价地清掉本地会话。
    sessionStorage.removeItem(MOCK_SESSION_KEY)
  },

  async register(payload: RegisterRequest): Promise<AuthResult> {
    await delay()
    if (!payload.phoneVerificationToken) {
      throw new ApiError('请先完成手机号验证', 'PHONE_VERIFICATION_REQUIRED', 422)
    }
    consumeGrant(payload.phoneVerificationToken, payload.phone, 'registration')
    return {
      user: {
        id: `mock-user-${Date.now()}`,
        username: payload.username,
        realName: payload.realName,
        gender: payload.gender,
        role: 'user',
        phoneMasked: maskPhone(payload.phone),
        idCardMasked: maskIdCard(payload.idCard),
        phoneVerified: true,
        registeredAt: new Date().toISOString(),
      },
    }
  },

  async login(payload: LoginRequest): Promise<AuthResult> {
    await delay()
    const user: AuthUser = {
      id: 'mock-user',
      username: payload.username,
      realName: payload.username,
      gender: 'private',
      role: 'user',
      phoneMasked: maskPhone(MOCK_PHONE),
      phoneVerified: false,
      registeredAt: new Date().toISOString(),
    }
    saveSafeSession(user)
    return { user }
  },

  async refresh(): Promise<AuthResult> {
    const user = await this.getCurrentUser()
    return { user }
  },

  async logout(): Promise<void> {
    await delay()
    sessionStorage.removeItem(MOCK_SESSION_KEY)
  },

  async getCurrentUser(): Promise<AuthUser> {
    await delay()
    const user = readSafeSession()
    if (!user) throw new ApiError('当前未登录', 'UNAUTHORIZED', 401)
    return user
  },
}