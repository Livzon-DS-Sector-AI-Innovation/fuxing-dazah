'use server'

// 工具箱写操作：上传文件执行工具步骤（multipart 转发）、工具配置、使用权限

import { revalidatePath } from 'next/cache'

import { getAuthHeaders } from '@/lib/auth'

import type { StepRunData, ToolConfig } from '@/types/toolbox'

// Server Action 内不 throw：生产构建会抹掉抛出的错误消息（只留 digest），
// 前端只能看到 "An error occurred in the Server Components render"，后端返回的
// 报错原因全部丢失。改为结构化返回，由调用方展示 error。
type ActionResult<T> = { success: true; data: T } | { success: false; error: string }

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

export async function runToolStep(formData: FormData): Promise<ActionResult<StepRunData>> {
  const toolId = formData.get('tool_id')
  const stepId = formData.get('step_id')
  if (!toolId || !stepId) return { success: false, error: '缺少 tool_id/step_id' }

  try {
    // multipart 转发：不设 Content-Type，让 fetch 自动带 boundary
    const headers = await getAuthHeaders()
    delete headers['Content-Type']

    const res = await fetch(`${API_BASE}/api/v1/toolbox/tools/${toolId}/steps/${stepId}/run`, {
      method: 'POST',
      headers,
      body: formData,
    })
    const json = await res.json().catch(() => null)
    if (!res.ok || !json) {
      return { success: false, error: json?.message || `执行失败: ${res.status}` }
    }
    return { success: true, data: json.data as StepRunData }
  } catch (err) {
    return { success: false, error: (err as Error).message || '执行失败' }
  }
}

/** 更新工具配置（整体覆盖后端 {tool_id}_config.json）。 */
export async function updateToolConfig(
  toolId: string,
  config: ToolConfig,
): Promise<ActionResult<ToolConfig>> {
  try {
    const headers = await getAuthHeaders()
    const res = await fetch(`${API_BASE}/api/v1/toolbox/tools/${toolId}/config`, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })
    const json = await res.json().catch(() => null)
    if (!res.ok || !json) {
      return { success: false, error: json?.message || `保存失败: ${res.status}` }
    }
    return { success: true, data: json.data as ToolConfig }
  } catch (err) {
    return { success: false, error: (err as Error).message || '保存失败' }
  }
}

/** 整体替换某工具的使用/配置授权名单（仅系统超级管理员）。 */
export async function updateToolGrants(
  toolId: string,
  useUserIds: string[],
  configUserIds: string[],
): Promise<ActionResult<null>> {
  try {
    const headers = await getAuthHeaders()
    const res = await fetch(`${API_BASE}/api/v1/toolbox/tools/${toolId}/grants`, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_user_ids: useUserIds, config_user_ids: configUserIds }),
    })
    const json = await res.json().catch(() => null)
    if (!res.ok || !json) {
      return { success: false, error: json?.message || `保存失败: ${res.status}` }
    }
    revalidatePath('/toolbox/permissions')
    return { success: true, data: null }
  } catch (err) {
    return { success: false, error: (err as Error).message || '保存失败' }
  }
}
