import { describe, expect, it } from 'vitest'
import { ApiError, getApiErrorMessage, sanitizeApiMessage } from './http'

describe('服务端文案过滤', () => {
  it('放行正常的短句，并去掉首尾空白', () => {
    expect(sanitizeApiMessage('登录状态已失效，请重新登录')).toBe('登录状态已失效，请重新登录')
    expect(sanitizeApiMessage('  请求参数有误  ')).toBe('请求参数有误')
  })

  it('丢弃非字符串，避免对象被渲染到界面上', () => {
    expect(sanitizeApiMessage(undefined)).toBeUndefined()
    expect(sanitizeApiMessage(null)).toBeUndefined()
    expect(sanitizeApiMessage({ detail: 'x' })).toBeUndefined()
    expect(sanitizeApiMessage(['a'])).toBeUndefined()
    expect(sanitizeApiMessage(500)).toBeUndefined()
  })

  it('丢弃空串与超长内容', () => {
    expect(sanitizeApiMessage('')).toBeUndefined()
    expect(sanitizeApiMessage('   ')).toBeUndefined()
    expect(sanitizeApiMessage('啊'.repeat(121))).toBeUndefined()
    expect(sanitizeApiMessage('啊'.repeat(120))).toBe('啊'.repeat(120))
  })

  it('丢弃 JSON、HTML 与多行堆栈', () => {
    expect(sanitizeApiMessage('{"detail":[{"msg":"field required"}]}')).toBeUndefined()
    expect(sanitizeApiMessage('["a","b"]')).toBeUndefined()
    expect(sanitizeApiMessage('<html><body>502 Bad Gateway</body></html>')).toBeUndefined()
    expect(sanitizeApiMessage('Traceback:\n  File "app.py", line 1')).toBeUndefined()
    expect(sanitizeApiMessage('第一行\r\n第二行')).toBeUndefined()
  })
})

describe('错误文案出口', () => {
  it('非 ApiError 一律给通用文案，不泄漏原始异常信息', () => {
    expect(getApiErrorMessage(new SyntaxError('Unexpected token < in JSON'))).toBe(
      '发生未知错误，请稍后重试',
    )
    expect(getApiErrorMessage('字符串')).toBe('发生未知错误，请稍后重试')
    expect(getApiErrorMessage(undefined)).toBe('发生未知错误，请稍后重试')
  })

  it('ApiError 的正常文案原样返回', () => {
    expect(getApiErrorMessage(new ApiError('请求已取消', 'REQUEST_CANCELLED'))).toBe('请求已取消')
  })

  it('ApiError 里夹带结构化内容时退回通用文案', () => {
    const leaked = new ApiError('{"detail":"boom"}', 'HTTP_500', 500)
    expect(getApiErrorMessage(leaked)).toBe('请求失败，请稍后重试')
  })

  it('任何情况下返回值都不含原始 JSON 或 HTML 片段', () => {
    const samples: unknown[] = [
      new ApiError('{"a":1}', 'X'),
      new ApiError('<html>err</html>', 'X'),
      new SyntaxError('Unexpected token } in JSON at position 0'),
      '{"raw":"json"}',
    ]

    for (const sample of samples) {
      expect(getApiErrorMessage(sample)).not.toMatch(/[{}[\]<>]/)
    }
  })
})