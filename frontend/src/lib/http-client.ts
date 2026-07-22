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
    const body = await res.text().catch(() => '')
    let msg = `请求失败: ${res.status}`
    try { msg = JSON.parse(body).message || msg } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function apiGet<T>(url: string, options?: RequestInit): Promise<T> {
  const json = await request<T>(url, { ...options, method: 'GET' })
  return (json as any).data ?? json
}

export async function apiPost<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
  const json = await request<T>(url, {
    ...options,
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
  return (json as any).data ?? json
}

export async function apiPut<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
  const json = await request<T>(url, {
    ...options,
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
  return (json as any).data ?? json
}

export async function apiDelete<T>(url: string, options?: RequestInit): Promise<T> {
  const json = await request<T>(url, { ...options, method: 'DELETE' })
  return (json as any).data ?? json
}

// ── 分页请求（兼容后端 { data, meta } 格式） ──

export async function apiFetchPaginated<T>(
  url: string,
  options?: RequestInit,
): Promise<{ items: T[]; total: number; page: number; page_size: number }> {
  const result = await request<any>(url, options)
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}
