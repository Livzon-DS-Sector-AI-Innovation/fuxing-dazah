'use server'

// 工具箱写操作：上传文件执行工具步骤（multipart 转发）

import { getAuthHeaders } from '@/lib/auth'

import type { StepRunData } from '@/types/toolbox'

export async function runToolStep(formData: FormData): Promise<StepRunData> {
  const base = process.env.API_BASE_URL || 'http://localhost:8000'
  const toolId = formData.get('tool_id')
  const stepId = formData.get('step_id')
  if (!toolId || !stepId) throw new Error('缺少 tool_id/step_id')

  // multipart 转发：不设 Content-Type，让 fetch 自动带 boundary
  const headers = await getAuthHeaders()
  delete headers['Content-Type']

  const res = await fetch(`${base}/api/v1/toolbox/tools/${toolId}/steps/${stepId}/run`, {
    method: 'POST',
    headers,
    body: formData,
  })
  const json = await res.json().catch(() => null)
  if (!res.ok || !json) {
    throw new Error(json?.message || `执行失败: ${res.status}`)
  }
  return json.data as StepRunData
}
