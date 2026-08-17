'use client'

// 工具箱读接口（React Query 不需要：数据由 page.tsx 服务端取、写操作走 server action）

import { apiGet } from '@/lib/http-client'
import type { ExecutionInfo, ToolInfo } from '@/types/toolbox'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export function fetchToolList(): Promise<ToolInfo[]> {
  return apiGet<ToolInfo[]>(`${API_BASE}/api/v1/toolbox/tools`)
}

export function fetchExecution(executionId: string): Promise<ExecutionInfo> {
  return apiGet<ExecutionInfo>(`${API_BASE}/api/v1/toolbox/executions/${executionId}`)
}

/** 下载执行产物（凭 cookie 认证，浏览器自动携带）。 */
export async function fetchFileDownload(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: 'include' })
  if (!res.ok) throw new Error(`下载失败: ${res.status}`)
  return res.blob()
}
