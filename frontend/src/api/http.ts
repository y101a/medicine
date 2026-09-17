import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'

export interface ApiErrorPayload {
  code?: string
  message?: string
  details?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly status?: number
  readonly details?: unknown

  constructor(message: string, code: string, status?: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

const DEFAULT_TIMEOUT_MS = 15_000

function getTimeoutMs() {
  const configuredTimeout = Number(import.meta.env.VITE_API_TIMEOUT_MS)
  return Number.isFinite(configuredTimeout) && configuredTimeout > 0
    ? configuredTimeout
    : DEFAULT_TIMEOUT_MS
}

function getStatusMessage(status?: number) {
  const messages: Record<number, string> = {
    400: '请求参数有误，请检查后重试',
    401: '登录状态已失效，请重新登录',
    403: '您没有权限执行此操作',
    404: '请求的内容不存在',
    409: '提交请求与当前数据状态冲突',
    422: '提交的信息校验未通过',
    429: '请求过于频繁，请稍后再试',
    500: '服务器暂时无法处理请求',
    502: '服务连接异常，请稍后再试',
    503: '服务暂时不可用，请稍后再试',
    504: '服务器响应超时，请稍后再试',
  }

  return status ? messages[status] : undefined
}

function normalizeError(error: AxiosError<ApiErrorPayload>) {
  if (axios.isCancel(error)) {
    return new ApiError('请求已取消', 'REQUEST_CANCELLED')
  }

  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return new ApiError('请求超时，请检查网络后重试', 'REQUEST_TIMEOUT')
  }

  if (!error.response) {
    return new ApiError('无法连接服务器，请检查网络或稍后重试', 'NETWORK_ERROR')
  }

  const { status, data } = error.response
  const message = data?.message || getStatusMessage(status) || '请求失败，请稍后重试'
  const code = data?.code || `HTTP_${status}`

  return new ApiError(message, code, status, data?.details)
}

let unauthorizedHandler: (() => void) | undefined

export function setUnauthorizedHandler(handler: () => void) {
  unauthorizedHandler = handler
}

export const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1',
  timeout: getTimeoutMs(),
  withCredentials: true,
  headers: {
    Accept: 'application/json',
  },
})

const refreshClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1',
  timeout: getTimeoutMs(),
  withCredentials: true,
  headers: {
    Accept: 'application/json',
  },
})

type RetryableRequestConfig = InternalAxiosRequestConfig & {
  _authRetry?: boolean
}

let refreshRequest: Promise<unknown> | null = null

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const apiError = normalizeError(error)
    const requestUrl = error.config?.url || ''
    const isCredentialAttempt = requestUrl.endsWith('/auth/login')
      || requestUrl.endsWith('/auth/register')
    const isRefreshAttempt = requestUrl.endsWith('/auth/refresh')
    const requestConfig = error.config as RetryableRequestConfig | undefined

    if (
      apiError.status === 401
      && !isCredentialAttempt
      && !isRefreshAttempt
      && requestConfig
      && !requestConfig._authRetry
    ) {
      requestConfig._authRetry = true
      try {
        refreshRequest ??= refreshClient.post('/auth/refresh')
        await refreshRequest
        return await http(requestConfig)
      } catch {
        unauthorizedHandler?.()
      } finally {
        refreshRequest = null
      }
    } else if (apiError.status === 401 && !isCredentialAttempt) {
      unauthorizedHandler?.()
    }

    return Promise.reject(apiError)
  },
)

export function getApiErrorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : '发生未知错误，请稍后重试'
}

export default http
