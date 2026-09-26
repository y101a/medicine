import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '../api/auth'
import { usersApi } from '../api/users'
import type { UpdateProfileRequest } from '../types/auth'
import type {
  AuthUser,
  LoginRequest,
  PasswordResetRequest,
  PhoneVerificationVerifyRequest,
  RegisterRequest,
} from '../types/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const initialized = ref(false)
  const pendingAction = ref<'login' | 'register' | 'logout' | null>(null)
  const avatarVersion = ref(Date.now())
  const isAuthenticated = computed(() => user.value !== null)
  const avatarUrl = computed(() => user.value ? usersApi.avatarUrl(avatarVersion.value) : '')

  async function initialize() {
    if (initialized.value) return
    try {
      user.value = await authApi.getCurrentUser()
      avatarVersion.value = Date.now()
    } catch {
      user.value = null
    } finally {
      initialized.value = true
    }
  }

  async function login(payload: LoginRequest) {
    pendingAction.value = 'login'
    try {
      const result = await authApi.login(payload)
      user.value = result.user
      avatarVersion.value = Date.now()
      initialized.value = true
      return result
    } finally {
      pendingAction.value = null
    }
  }

  async function register(payload: RegisterRequest) {
    pendingAction.value = 'register'
    try {
      return await authApi.register(payload)
    } finally {
      pendingAction.value = null
    }
  }

  async function logout() {
    pendingAction.value = 'logout'
    try {
      await authApi.logout()
    } finally {
      clearSession()
      pendingAction.value = null
    }
  }

  function clearSession() {
    user.value = null
    initialized.value = true
  }

  async function updateProfile(payload: UpdateProfileRequest) {
    const updated = await usersApi.updateProfile(payload)
    if (user.value?.id === updated.id) user.value = updated
    return updated
  }

  async function uploadAvatar(file: File) {
    await usersApi.uploadAvatar(file)
    avatarVersion.value = Math.max(Date.now(), avatarVersion.value + 1)
  }

  /** 删除账号与全部个人数据；成功后本地会话立即作废（后端要求验证当前密码）。 */
  async function deleteAccount(currentPassword: string) {
    await usersApi.deleteAccount(currentPassword)
    clearSession()
  }

  /**
   * 已有用户补验证：验证码由后端发给「当前账户已加密保存的手机号」，前端不传手机号。
   *
   * 成功后只改本地这一处 `phoneVerified`，不再多打一次 `/users/me`——接口是 204，
   * 没有响应体可读，而服务端语义就是「现在已验证」。
   */
  async function requestCurrentPhoneCode() {
    return await authApi.requestCurrentPhoneCode()
  }

  async function confirmCurrentPhone(payload: PhoneVerificationVerifyRequest) {
    await authApi.confirmCurrentPhone(payload)
    if (user.value) user.value = { ...user.value, phoneVerified: true }
  }

  /**
   * 短信找回密码。
   *
   * 成功后必须清掉本地会话：5.4 要求后端撤销该用户全部刷新会话并提升认证版本，
   * 已经签发出去的旧访问令牌也随之下线，前端留着登录态只会不断撞 401。
   */
  async function resetPassword(payload: PasswordResetRequest) {
    await authApi.resetPassword(payload)
    clearSession()
  }

  return {
    user,
    initialized,
    pendingAction,
    avatarUrl,
    isAuthenticated,
    initialize,
    login,
    register,
    logout,
    clearSession,
    updateProfile,
    uploadAvatar,
    deleteAccount,
    requestCurrentPhoneCode,
    confirmCurrentPhone,
    resetPassword,
  }
})
