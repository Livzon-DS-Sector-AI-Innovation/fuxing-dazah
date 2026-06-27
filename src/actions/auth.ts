'use server'

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import type { User, ImpersonationStatus } from '@/types/user'

const API_BASE = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export async function getCurrentUser(): Promise<User | null> {
  const cookieStore = await cookies()
  const token = cookieStore.get('auth_token')

  if (!token?.value) return null

  try {
    const res = await fetch(`${API_BASE}/api/v1/identity/me`, {
      headers: { Authorization: `Bearer ${token.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export async function logout() {
  const cookieStore = await cookies()
  cookieStore.delete('auth_token')
  revalidatePath('/')
  redirect('/login')
}

export async function startImpersonate(targetUserId: string): Promise<void> {
  const cookieStore = await cookies()
  const token = cookieStore.get('auth_token')
  if (!token?.value) throw new Error('未登录')

  const res = await fetch(`${API_BASE}/api/v1/identity/impersonate/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token.value}`,
    },
    body: JSON.stringify({ target_user_id: targetUserId }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || err.message || `开始代理失败 (${res.status})`)
  }

  const body = await res.json()
  const data = body.data
  if (!data?.token) throw new Error('服务端未返回代理 token')

  // 服务端设置 httpOnly cookie
  const isHttps = process.env.NODE_ENV === 'production'
  cookieStore.set('impersonate_token', data.token, {
    httpOnly: true,
    secure: isHttps,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 2, // 2 hours
  })
}

export async function stopImpersonate(): Promise<void> {
  const cookieStore = await cookies()
  cookieStore.delete('impersonate_token')
}

const NO_IMPERSONATION: ImpersonationStatus = { is_impersonating: false, real_user: null, target_user: null, expires_at: null }

export async function getImpersonationStatus(): Promise<ImpersonationStatus> {
  const cookieStore = await cookies()
  const token = cookieStore.get('auth_token')
  const impCookie = cookieStore.get('impersonate_token')
  if (!token?.value) return NO_IMPERSONATION

  try {
    const headers: Record<string, string> = { Authorization: `Bearer ${token.value}` }
    if (impCookie?.value) {
      headers['Cookie'] = `impersonate_token=${impCookie.value}`
    }
    const res = await fetch(`${API_BASE}/api/v1/identity/impersonate/status`, {
      headers,
      cache: 'no-store',
    })
    if (!res.ok) return NO_IMPERSONATION
    const body = await res.json()
    return body.data as ImpersonationStatus
  } catch {
    return NO_IMPERSONATION
  }
}
