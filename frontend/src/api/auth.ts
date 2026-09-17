import http from './http'
import { mockAuthApi } from './mockAuth'
import type { AuthResult, AuthUser, LoginRequest, RegisterRequest } from '../types/auth'

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
}
