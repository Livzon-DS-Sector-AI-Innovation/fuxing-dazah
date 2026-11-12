import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const API_BASE = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/**
 * 从请求头中获取用户实际访问的地址（而非 Docker 容器内部 hostname）。
 * 优先读取反向代理转发的 X-Forwarded-Host，否则使用浏览器发送的 Host 头。
 */
function getOrigin(request: NextRequest): string {
  const forwardedHost = request.headers.get('x-forwarded-host')
  const forwardedProto = request.headers.get('x-forwarded-proto')
  const host = forwardedHost || request.headers.get('host')
  const protocol = forwardedProto || request.nextUrl.protocol.replace(':', '')
  return `${protocol}://${host}`
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get('code')
  const error = request.nextUrl.searchParams.get('error')
  const origin = getOrigin(request)

  if (error) {
    return NextResponse.redirect(new URL(`/login?error=${error}`, origin))
  }

  if (!code) {
    return NextResponse.redirect(new URL('/login?error=no_code', origin))
  }

  // 用一次性 code 在服务端兑换 JWT（code 120 秒过期、仅一次），
  // token 始终不经过浏览器 URL / 历史
  let token: string | null = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/identity/auth/exchange?code=${code}`, {
      cache: 'no-store',
    })
    if (res.ok) {
      const body = await res.json()
      token = body?.data?.token ?? null
    }
  } catch {
    token = null
  }

  if (!token) {
    return NextResponse.redirect(new URL('/login?error=exchange_failed', origin))
  }

  const cookieStore = await cookies()
  const isHttps = request.nextUrl.protocol === 'https:'
  cookieStore.set('auth_token', token, {
    httpOnly: true,
    secure: isHttps,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 24, // 与后端 JWT_EXPIRE_SECONDS(24h) 对齐
  })

  return NextResponse.redirect(new URL('/welcome', origin))
}
