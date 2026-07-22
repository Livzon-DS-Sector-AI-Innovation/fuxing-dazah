import 'server-only'
import { setTokenGetter } from '@/lib/http-client'
import { getServerToken, getImpersonateToken } from '@/lib/auth'

// 注册服务端 token getter（仅存函数引用，不触发 cookies()）
// 实际 token 获取在 http-client 首次发起请求时惰性执行
// 同时转发 impersonate_token cookie，确保代理身份在 Server Component fetch 中生效
setTokenGetter(async () => {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()
  return {
    token,
    cookieHeader: impToken ? `impersonate_token=${impToken}` : undefined,
  }
})
