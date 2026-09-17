import { ApiError } from './http'
import type { AuthResult, AuthUser, LoginRequest, RegisterRequest } from '../types/auth'

const MOCK_SESSION_KEY = 'medical-assistant:mock-user'
const MOCK_DELAY_MS = 500

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

export const mockAuthApi = {
  async register(payload: RegisterRequest): Promise<AuthResult> {
    await delay()
    return {
      user: {
        id: `mock-user-${Date.now()}`,
        username: payload.username,
        realName: payload.realName,
        gender: payload.gender,
        role: 'user',
        phoneMasked: maskPhone(payload.phone),
        idCardMasked: maskIdCard(payload.idCard),
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
