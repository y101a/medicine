import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MODEL_PREFERENCE_STORAGE_KEY_PREFIX,
  readSelectedModelId,
  rememberSelectedModelId,
} from './modelPreference'

describe('modelPreference', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('restores the model selected before a page refresh', () => {
    rememberSelectedModelId('user-1', 'qwen-plus')

    expect(window.localStorage.getItem(`${MODEL_PREFERENCE_STORAGE_KEY_PREFIX}:user-1`))
      .toBe('qwen-plus')
    expect(readSelectedModelId('user-1')).toBe('qwen-plus')
  })

  it('ignores empty model identifiers', () => {
    rememberSelectedModelId('user-1', '')

    expect(readSelectedModelId('user-1')).toBe('')
  })

  it('keeps different users preferences isolated', () => {
    rememberSelectedModelId('user-1', 'qwen-plus')
    rememberSelectedModelId('user-2', 'deepseek-v4-flash')

    expect(readSelectedModelId('user-1')).toBe('qwen-plus')
    expect(readSelectedModelId('user-2')).toBe('deepseek-v4-flash')
  })

  it('falls back safely when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })

    expect(readSelectedModelId('user-1')).toBe('')
  })
})
