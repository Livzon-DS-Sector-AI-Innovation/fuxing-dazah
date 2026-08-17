'use server'

// 工具箱写操作：上传文件执行工具步骤（multipart 转发）

import { cookies } from 'next/headers'

import type { StepRunData } from '@/types/toolbox'

export async function runToolStep(formData: FormData): Promise<StepRunData> {
  const cookieStore = await cookies()
  const token = cookieStore.get('auth_token')?.value
  const base = process.env.API_BASE_URL || 'http://localhost:8000'
  const toolId = formData.get('tool_id')
  const stepId = formData.get('step_id')

  const res = await fetch(`${base}/api/v1/toolbox/tools/${toolId}/steps/${stepId}/run`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData, // FormData 直接转发（fetch 自动设置 multipart boundary）
  })
  const json = await res.json().catch(() => null)
  if (!res.ok || !json) {
    throw new Error(json?.message || `执行失败: ${res.status}`)
  }
  return json.data as StepRunData
}
