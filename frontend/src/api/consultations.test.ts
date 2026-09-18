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

it('非 OK 响应带回结构化报文时，不把原始内容显示给用户', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false,
    status: 502,
    json: async () => ({ detail: [{ msg: 'upstream failed' }] }),
  }))

  await expect(consultationsApi.stream(
    'c1', 'r1', 'test-model', 'plain', new AbortController().signal, vi.fn(), vi.fn(),
  )).rejects.toMatchObject({ message: 'AI 服务请求失败', code: 'HTTP_502' })
})

it('流中混入坏帧时明确报错，不把残缺内容当成回答', async () => {
  const bytes = new TextEncoder().encode('{"type":"delta","content":"片段"}\n{坏帧\n')
  let readCount = 0
  const cancel = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => readCount++ === 0
          ? { done: false, value: bytes }
          : { done: true, value: undefined },
        cancel,
      }),
    },
  }))

  const onDelta = vi.fn()
  await expect(consultationsApi.stream(
    'c1', 'r1', 'test-model', 'plain', new AbortController().signal, onDelta, vi.fn(),
  )).rejects.toMatchObject({ message: '回答数据格式异常，请重试', code: 'STREAM_MALFORMED' })
  // 坏帧之前的正常内容已经送达，但不会再继续往下读。
  expect(onDelta).toHaveBeenCalledWith('片段')
  expect(cancel).toHaveBeenCalledOnce()
})
