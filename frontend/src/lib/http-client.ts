// ═══════════════════════════════════════════════════════════════
//  统一 HTTP 客户端
//  惰性 token 注入，兼容 Server Component 和 Client Component
// ═══════════════════════════════════════════════════════════════
import { cache } from 'react'

// ── 惰性 token 管理 ──
let _tokenGetter: (() => Promise<{ token?: string; cookieHeader?: string }>) | undefined

/** 注册 token 获取函数（http-server.ts 在服务端自动调用） */
export function setTokenGetter(getter: () => Promise<{ token?: string; cookieHeader?: string }>): void {
  _tokenGetter = getter
}

// React.cache() 提供请求级缓存：同一次渲染（一个 HTTP 请求）内多次调用复用结果，
// 不同请求各自独立，杜绝 token/impersonate_token 跨请求泄露。
const _resolveAuth = cache(async () => {
  if (!_tokenGetter) return { token: undefined as string | undefined, cookieHeader: undefined as string | undefined }
  return _tokenGetter()
})

function formatApiErrorMessage(body: unknown, status: number): string {
  const payload = body && typeof body === 'object'
    ? body as { message?: unknown; detail?: unknown; request_id?: unknown }
    : {}
  const detail = typeof payload.detail === 'string'
    ? payload.detail
    : Array.isArray(payload.detail)
      ? payload.detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) return String((item as { msg?: unknown }).msg || '')
          return String(item || '')
        })
        .filter(Boolean)
        .join('；')
      : payload.detail != null
        ? String(payload.detail)
        : ''
  const message = typeof payload.message === 'string' && payload.message
    ? payload.message
    : detail || `请求失败: ${status}`
  const withDetail = detail && detail !== message ? `${message}：${detail}` : message
  const requestId = typeof payload.request_id === 'string' ? payload.request_id : ''
  return requestId && !withDetail.includes(requestId)
    ? `${withDetail}（错误编号：${requestId}）`
    : withDetail
}

type ApiDataEnvelope<T> = { data?: T | null }
type ApiPageEnvelope<T> = {
  data?: T[]
  meta?: { total?: number; page?: number; page_size?: number }
}

function unwrapApiData<T>(value: T | ApiDataEnvelope<T>): T {
  if (value && typeof value === 'object' && 'data' in value) {
    const data = (value as ApiDataEnvelope<T>).data
    if (data !== undefined && data !== null) return data
  }
  return value as T
}

// ── 基础请求 ──

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const { token, cookieHeader } = await _resolveAuth()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (cookieHeader) headers['Cookie'] = cookieHeader

  const res = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  })
  if (!res.ok) {
    // ponytail: client-side 401 → redirect login, re-auth clears expired cookie
    if (typeof window !== 'undefined' && res.status === 401) {
      window.location.href = '/login'
      throw new Error('登录已过期，正在跳转...')
    }
    const body = await res.text().catch(() => '')
    let parsed: unknown = null
    try { parsed = JSON.parse(body) } catch { /* 非 JSON 响应使用状态码 */ }
    const msg = formatApiErrorMessage(parsed, res.status)
    // 携带 status 便于调用方区分 403（无权限）与 5xx/网络错误
    const err = new Error(msg) as Error & { status: number }
    err.status = res.status
    throw err
  }
  return res.json()
}

export async function apiGet<T>(url: string, options?: RequestInit): Promise<T> {
  const json = await request<T | ApiDataEnvelope<T>>(url, { ...options, method: 'GET' })
  return unwrapApiData(json)
}

export async function apiPost<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
  const json = await request<T | ApiDataEnvelope<T>>(url, {
    ...options,
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
  return unwrapApiData(json)
}

export async function apiPut<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
  const json = await request<T | ApiDataEnvelope<T>>(url, {
    ...options,
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
  return unwrapApiData(json)
}

export async function apiDelete<T>(url: string, options?: RequestInit): Promise<T> {
  const json = await request<T | ApiDataEnvelope<T>>(url, { ...options, method: 'DELETE' })
  return unwrapApiData(json)
}

// ── 分页请求（兼容后端 { data, meta } 格式） ──

export async function apiFetchPaginated<T>(
  url: string,
  options?: RequestInit,
): Promise<{ items: T[]; total: number; page: number; page_size: number }> {
  const result = await request<ApiPageEnvelope<T> | T[]>(url, options)
  const page = Array.isArray(result) ? { data: result } : result
  return {
    items: page.data || [],
    total: page.meta?.total || 0,
    page: page.meta?.page || 1,
    page_size: page.meta?.page_size || 20,
  }
}
