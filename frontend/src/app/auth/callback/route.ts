import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

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
  const token = request.nextUrl.searchParams.get('token')
  const error = request.nextUrl.searchParams.get('error')
  const origin = getOrigin(request)

  if (error) {
    return NextResponse.redirect(new URL(`/login?error=${error}`, origin))
  }

  if (!token) {
    return NextResponse.redirect(new URL('/login?error=no_token', origin))
  }

  const cookieStore = await cookies()
  const isHttps = request.nextUrl.protocol === 'https:'
  cookieStore.set('auth_token', token, {
    httpOnly: true,
    secure: isHttps,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 7,
  })

  return NextResponse.redirect(new URL('/welcome', origin))
}
