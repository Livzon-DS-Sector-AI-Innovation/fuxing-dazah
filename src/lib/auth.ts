import { cookies } from 'next/headers'

export async function getServerToken(): Promise<string | undefined> {
  const cookieStore = await cookies()
  const token = cookieStore.get('auth_token')
  return token?.value
}

/** 获取代理身份 cookie（impersonate_token），用于转发给后端 API */
export async function getImpersonateToken(): Promise<string | undefined> {
  const cookieStore = await cookies()
  const token = cookieStore.get('impersonate_token')
  return token?.value
}

/** 返回带 Authorization 的 headers 对象，供 Server Actions 调用后端 API。
 *  自动转发 impersonate_token cookie，确保代理身份在服务端请求中生效。 */
export async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = await getServerToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const impToken = await getImpersonateToken()
  if (impToken) {
    headers['Cookie'] = `impersonate_token=${impToken}`
  }
  return headers
}
