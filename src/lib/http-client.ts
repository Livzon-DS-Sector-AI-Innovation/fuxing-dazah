// ═══════════════════════════════════════════════════════════════
//  统一 HTTP 客户端
//  惰性 token 注入，兼容 Server Component 和 Client Component
// ═══════════════════════════════════════════════════════════════

// ── 惰性 token 管理 ──
let _tokenGetter: (() => Promise<{ token?: string; cookieHeader?: string }>) | undefined
let _token: string | undefined
let _cookieHeader: string | undefined
let _tokenReady = false

/** 注册 token 获取函数（http-server.ts 在服务端自动调用） */
export function setTokenGetter(getter: () => Promise<{ token?: string; cookieHeader?: string }>): void {
  _tokenGetter = getter
}

async function ensureToken(): Promise<void> {
  if (_tokenReady) return
  _tokenReady = true
  if (_tokenGetter) {
    const result = await _tokenGetter()
    _token = result.token
    _cookieHeader = result.cookieHeader
  }
}

function authHeaders(extraHeaders?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (_token) headers['Authorization'] = `Bearer ${_token}`
  if (_cookieHeader) headers['Cookie'] = _cookieHeader
  return { ...headers, ...extraHeaders }
}

// ── 基础请求 ──

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  await ensureToken()
  const res = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: authHeaders(init?.headers as Record<string, string> | undefined),
  })
  if (!res.ok) {
    throw new Error(`请求失败: ${res.status} ${res.statusText}`)
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
