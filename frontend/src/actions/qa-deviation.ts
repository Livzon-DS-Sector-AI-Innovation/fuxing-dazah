'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type {
  CapaActionPatchInput,
  CapaCreateInput,
  CapaDetail,
  CapaTransitionAction,
  CapaUpdateInput,
  DeviationAiAssistInput,
  DeviationAiAssistResult,
  DeviationAttachment,
  DeviationCreateInput,
  DeviationDetail,
  DeviationTransitionAction,
  DeviationUpdateInput,
} from '@/types/qa-deviation'

const BASE = `${API_BASE}/qa`

function revalidateDeviation(id?: string) {
  revalidatePath('/qa/deviation')
  if (id) revalidatePath(`/qa/deviation/${id}`)
}

// ───────────────────────── 偏差 ─────────────────────────

export async function createDeviation(input: DeviationCreateInput): Promise<ActionResult<DeviationDetail>> {
  const result = await actionFetch<DeviationDetail>(`${BASE}/deviations`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateDeviation()
  return result
}

export async function updateDeviation(id: string, input: DeviationUpdateInput): Promise<ActionResult<DeviationDetail>> {
  const result = await actionFetch<DeviationDetail>(`${BASE}/deviations/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateDeviation(id)
  return result
}

export async function transitionDeviation(
  id: string,
  action: DeviationTransitionAction,
  comment?: string,
): Promise<ActionResult<DeviationDetail>> {
  const result = await actionFetch<DeviationDetail>(`${BASE}/deviations/${id}/transition`, {
    method: 'POST',
    body: JSON.stringify({ action, comment: comment || undefined }),
  })
  if (result.success) revalidateDeviation(id)
  return result
}

export async function extendDeviation(
  id: string,
  newDueDate: string,
  reason: string,
): Promise<ActionResult<DeviationDetail>> {
  const result = await actionFetch<DeviationDetail>(`${BASE}/deviations/${id}/extend`, {
    method: 'POST',
    body: JSON.stringify({ new_due_date: newDueDate, reason }),
  })
  if (result.success) revalidateDeviation(id)
  return result
}

export async function deleteDeviation(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/deviations/${id}`, { method: 'DELETE' })
  if (result.success) revalidateDeviation()
  return result
}

export async function uploadDeviationAttachment(
  id: string,
  formData: FormData,
): Promise<ActionResult<DeviationAttachment>> {
  try {
    const authHeaders = await getAuthHeaders()
    // 绝不能手工设置 multipart Content-Type，边界由 fetch 自动生成。
    const headers = { ...authHeaders }
    delete headers['Content-Type']
    const response = await fetch(`${BASE}/deviations/${id}/attachments`, {
      method: 'POST',
      headers,
      body: formData,
    })
    const text = await response.text().catch(() => '')
    let json: unknown = null
    try { json = text ? JSON.parse(text) : null } catch { /* ignore malformed error */ }
    if (!response.ok) {
      const body = json as { message?: string; detail?: string } | null
      return { success: false, error: body?.message || body?.detail || `请求失败: ${response.status}` }
    }
    revalidateDeviation(id)
    return { success: true, data: ((json as { data?: DeviationAttachment } | null)?.data ?? null) }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : '网络错误' }
  }
}

export async function deleteDeviationAttachment(id: string, attachmentId: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/deviations/${id}/attachments/${attachmentId}`, { method: 'DELETE' })
  if (result.success) revalidateDeviation(id)
  return result
}

// ───────────────────────── AI 辅助 ─────────────────────────

export async function deviationAiAssist(
  input: DeviationAiAssistInput,
): Promise<ActionResult<DeviationAiAssistResult>> {
  // 纯建议接口无副作用，不需要 revalidate。
  return actionFetch<DeviationAiAssistResult>(`${BASE}/deviations/ai-assist`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

// ───────────────────────── CAPA ─────────────────────────

function revalidateCapa(deviationId?: string) {
  revalidatePath('/qa/capa')
  if (deviationId) revalidateDeviation(deviationId)
}

export async function createCapa(input: CapaCreateInput): Promise<ActionResult<CapaDetail>> {
  const result = await actionFetch<CapaDetail>(`${BASE}/capas`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCapa(input.deviation_id)
  return result
}

export async function updateCapa(id: string, input: CapaUpdateInput): Promise<ActionResult<CapaDetail>> {
  const result = await actionFetch<CapaDetail>(`${BASE}/capas/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCapa(result.data?.deviation_id)
  return result
}

export async function patchCapaAction(
  id: string,
  actionId: string,
  input: CapaActionPatchInput,
): Promise<ActionResult<CapaDetail>> {
  const result = await actionFetch<CapaDetail>(`${BASE}/capas/${id}/actions/${actionId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCapa(result.data?.deviation_id)
  return result
}

export async function transitionCapa(
  id: string,
  action: CapaTransitionAction,
  comment?: string,
): Promise<ActionResult<CapaDetail>> {
  const result = await actionFetch<CapaDetail>(`${BASE}/capas/${id}/transition`, {
    method: 'POST',
    body: JSON.stringify({ action, comment: comment || undefined }),
  })
  if (result.success) revalidateCapa(result.data?.deviation_id)
  return result
}
