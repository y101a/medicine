import http from './http'
import type { AuthUser, UpdateProfileRequest } from '../types/auth'

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
  /** 删除账号与全部个人数据；后端要求验证当前密码（错的会返回 422 ACCOUNT_PASSWORD_INVALID）。 */
  async deleteAccount(currentPassword: string) {
    await http.delete('/users/me', { data: { currentPassword } })
  },
}
