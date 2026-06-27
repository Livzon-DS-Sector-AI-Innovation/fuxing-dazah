import { NextRequest, NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login', '/auth/callback', '/api']

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

export function proxy(request: NextRequest) {
  const token = request.cookies.get('auth_token')
  const { pathname } = request.nextUrl

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next()
  }

  if (!token?.value) {
    const origin = getOrigin(request)
    const loginUrl = new URL('/login', origin)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
