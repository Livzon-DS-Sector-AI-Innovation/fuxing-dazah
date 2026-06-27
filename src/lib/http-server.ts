import 'server-only'
import { setTokenGetter } from '@/lib/http-client'
import { getServerToken } from '@/lib/auth'

// 注册服务端 token getter（仅存函数引用，不触发 cookies()）
// 实际 token 获取在 http-client 首次发起请求时惰性执行
setTokenGetter(getServerToken)
