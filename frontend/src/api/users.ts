import http from './http'
import type {
  AuthUser,
  PhoneChangeCodeRequest,
  PhoneChangeRequest,
  PhoneVerificationChallenge,
  UpdateProfileRequest,
} from '../types/auth'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1').replace(/\/$/, '')

export const usersApi = {
  async updateProfile(payload: UpdateProfileRequest) {
    return (await http.patch<AuthUser>('/users/me', payload)).data
  },
  async uploadAvatar(file: File) {
    const data = new FormData()
    data.append('avatar', file)
    return (await http.put<{ avatarUrl: string }>('/users/me/avatar', data)).data
  },
  avatarUrl(version: number) {
    return `${apiBaseUrl}/users/me/avatar?v=${version}`
  },
  /**
   * 换绑手机号第一步：当前密码 + 新号码，验证码发给新号码（202）。
   *
   * 密码错 422 `ACCOUNT_PASSWORD_INVALID`、号码已被占用 409 `PHONE_EXISTS`、
   * 与当前号相同 422 `PHONE_UNCHANGED`、发送过频 429 `SMS_RATE_LIMITED`。
   */
  async requestPhoneChangeCode(payload: PhoneChangeCodeRequest) {
    return (
      await http.post<PhoneVerificationChallenge>(
        '/users/me/phone-verification/change-code',
        payload,
      )
    ).data
  },
  /** 换绑第二步：新号码 + 验证码；成功返回更新后的用户（掩码与验证状态都变了）。 */
  async changePhone(payload: PhoneChangeRequest) {
    return (await http.post<AuthUser>('/users/me/phone-verification/change', payload)).data
  },
  /** 删除账号与全部个人数据；后端要求验证当前密码（错的会返回 422 ACCOUNT_PASSWORD_INVALID）。 */
  async deleteAccount(currentPassword: string) {
    await http.delete('/users/me', { data: { currentPassword } })
  },
}
