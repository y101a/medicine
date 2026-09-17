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
}

export interface AuthResult {
  user: AuthUser
}

export interface UpdateProfileRequest {
  realName?: string
  gender?: Gender
}
