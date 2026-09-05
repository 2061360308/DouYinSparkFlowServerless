/**
 * HTTP 客户端：同源(dev 经 Vite 代理到 :8000)调用后端 JSON API。
 * - 携带会话 Cookie（credentials: 'include'）
 * - 写操作自动附带 X-CSRF-Token
 * - 统一错误：抛出带 status/detail 的 ApiError
 */

import { ref } from 'vue'

export const csrfToken = ref('')

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

/** 401 回调（由鉴权层注册，用于跳转登录）。 */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

async function request<T>(method: Method, path: string, body?: unknown, silent = false): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken.value

  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401 && !silent && onUnauthorized) {
    onUnauthorized()
  }

  let payload: unknown = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : response.statusText || '请求失败'
    throw new ApiError(response.status, detail)
  }
  return payload as T
}

export const http = {
  get: <T>(path: string, silent = false) => request<T>('GET', path, undefined, silent),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string, body?: unknown) => request<T>('DELETE', path, body),
}
