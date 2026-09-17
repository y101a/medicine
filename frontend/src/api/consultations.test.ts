import { afterEach, expect, it, vi } from 'vitest'
import { consultationsApi } from './consultations'

afterEach(() => vi.unstubAllGlobals())

it('读取流式 start 检索状态并保留回答消息，不把状态当正文', async () => {
  const lines = [
    { type: 'start', retrieval: {
      status: 'empty', gateReason: 'medical_content',
      webSearchStatus: 'failed', webSearchErrorCode: 'WEB_SEARCH_TIMEOUT',
      sources: [],
    } },
    { type: 'delta', content: '仅供科普。' },
    { type: 'done', message: {
      id: 'm1', role: 'assistant', content: '仅供科普。',
      sequence: 2, citations: [], createdAt: '2026-09-13T00:00:00Z',
    } },
  ].map(item => JSON.stringify(item)).join('\n') + '\n'
  const bytes = new TextEncoder().encode(lines)
  let readCount = 0
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => readCount++ === 0
          ? { done: false, value: bytes }
          : { done: true, value: undefined },
      }),
    },
  }))
  const onDelta = vi.fn()
  const onRetrieval = vi.fn()
  const result = await consultationsApi.stream(
    'c1', 'r1', 'test-model', 'plain', new AbortController().signal,
    onDelta, onRetrieval,
  )
  expect(onRetrieval).toHaveBeenCalledWith(expect.objectContaining({
    status: 'empty', webSearchStatus: 'failed', webSearchErrorCode: 'WEB_SEARCH_TIMEOUT',
  }))
  expect(onDelta).toHaveBeenCalledOnce()
  expect(onDelta).toHaveBeenCalledWith('仅供科普。')
  expect(result.citations).toEqual([])
})
