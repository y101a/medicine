import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from './auth'

async function finishMockRequest<T>(request: Promise<T>) {
  await vi.advanceTimersByTimeAsync(500)
  return request
}

describe('auth store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('登录后只保存安全的用户会话信息', async () => {
    const store = useAuthStore()
    await finishMockRequest(store.login({ username: 'tester', password: 'secret123' }))

    expect(store.isAuthenticated).toBe(true)
    expect(store.user?.username).toBe('tester')
    expect(sessionStorage.getItem('medical-assistant:mock-user')).not.toContain('secret123')
  })

  it('刷新初始化时可以恢复模拟登录状态', async () => {
    const firstStore = useAuthStore()
    await finishMockRequest(firstStore.login({ username: 'tester', password: 'secret123' }))

    setActivePinia(createPinia())
    const restoredStore = useAuthStore()
    await finishMockRequest(restoredStore.initialize())

    expect(restoredStore.isAuthenticated).toBe(true)
    expect(restoredStore.user?.username).toBe('tester')
  })

  it('退出后清除用户状态与模拟会话', async () => {
    const store = useAuthStore()
    await finishMockRequest(store.login({ username: 'tester', password: 'secret123' }))
    await finishMockRequest(store.logout())

    expect(store.isAuthenticated).toBe(false)
    expect(sessionStorage.getItem('medical-assistant:mock-user')).toBeNull()
  })
})
