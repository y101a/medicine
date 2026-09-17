import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '../api/auth'
import { usersApi } from '../api/users'
import type { UpdateProfileRequest } from '../types/auth'
import type { AuthUser, LoginRequest, RegisterRequest } from '../types/auth'

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
  }
})
