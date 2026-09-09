'use client'

// 工具箱客户端能力：执行产物下载、后台执行状态轮询。
// 工具列表/会话读取由 page.tsx 在服务端用 lib/http-client 的 apiGet 完成（自动带 token）。

import type { ExecutionInfo } from '@/types/toolbox'

/** 下载执行产物（凭 cookie 认证，浏览器自动携带）。 */
export async function fetchFileDownload(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: 'include' })
  if (!res.ok) throw new Error(`下载失败: ${res.status}`)
  return res.blob()
}

/** 轮询执行会话状态（后台执行工具：进度/结果/失败原因都在会话里，凭 cookie 认证）。
 * 401/403 挂 status 抛出：登录失效跳登录页，权限问题由调用方终止轮询，
 * 不与网络抖动混同计数（与 lib/http-client 的 401 处理同口径）。 */
export async function fetchExecutionState(executionId: string): Promise<ExecutionInfo> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  const res = await fetch(`${base}/api/v1/toolbox/executions/${executionId}`, {
    credentials: 'include',
  })
  const json = await res.json().catch(() => null)
  if (!res.ok || !json) {
    if (res.status === 401) {
      window.location.href = '/login'
      throw new Error('登录已过期，正在跳转...')
    }
    const err = new Error(json?.message || `获取执行状态失败: ${res.status}`) as Error & {
      status: number
    }
    err.status = res.status
    throw err
  }
  return json.data as ExecutionInfo
}
