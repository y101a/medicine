export type UserRole = 'user' | 'admin'
export type Gender = 'male' | 'female' | 'private'

export interface AuthUser {
  id: string
  username: string
  realName: string
  gender: Gender
  role: UserRole
  phoneMasked?: string
  idCardMasked?: string
  /**
   * 手机号是否已完成短信验证。
   *
   * 迁移前已存在的用户在补验证前为 `false`（不因为库里有手机号就当真）；
   * 迁移后新注册的用户为 `true`。设置页只在明确拿到 `false` 时提示补验证。
   */
  phoneVerified: boolean
  registeredAt: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  realName: string
  phone: string
  idCard: string
  gender: Gender
  password: string
  /** 注册必须先通过短信验证：这里放 5.2 换来的一次性令牌（purpose=registration）。 */
  phoneVerificationToken: string
}

export interface AuthResult {
  user: AuthUser
}

export interface UpdateProfileRequest {
  realName?: string
  gender?: Gender
  /** 改登录名（用户名）时必须同时给当前密码，后端要用它验一次身份。 */
  username?: string
  currentPassword?: string
}

/**
 * 公开验证码用途。只接受这两个值。
 *
 * 已登录用户的补验证与换绑手机号共用后端的 `phone_binding` 用途，但那两个接口
 * 不走公开的 `purpose` 字段，所以这里不列它。
 */
export type PhoneVerificationPurpose = 'registration' | 'password_reset'

export interface PhoneVerificationCodeRequest {
  phone: string
  purpose: PhoneVerificationPurpose
}

/** 发送验证码的响应（202）。`resendAfterSeconds` 是倒计时的唯一依据。 */
export interface PhoneVerificationChallenge {
  challengeId: string
  expiresInSeconds: number
  resendAfterSeconds: number
}

export interface PhoneVerificationVerifyRequest {
  challengeId: string
  code: string
}

/** 换绑手机号第一步：当前密码 + 新号码；后端验密码后把验证码发给**新号码**。 */
export interface PhoneChangeCodeRequest {
  phone: string
  currentPassword: string
}

/** 换绑第二步：新号码要再传一次，服务端才能把这串明文加密存下来。 */
export interface PhoneChangeRequest {
  phone: string
  challengeId: string
  code: string
}

/** 校验通过换来的**一次性**令牌，只绑定 challenge、手机号指纹与用途，不代表已登录。 */
export interface PhoneVerificationGrant {
  verificationToken: string
  expiresInSeconds: number
}

export interface PasswordResetRequest {
  phone: string
  verificationToken: string
  newPassword: string
}
