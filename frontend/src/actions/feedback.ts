'use server'

import { getAuthHeaders } from '@/lib/auth'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type { Feedback, FeedbackAttachment, FeedbackCreateInput } from '@/types/feedback'

const BASE = `${API_BASE}/feedback`

// 反馈没有服务端渲染的消费页面，不需要 revalidatePath；由 React Query 失效刷新。

export async function submitFeedback(input: FeedbackCreateInput): Promise<ActionResult<Feedback>> {
  return actionFetch<Feedback>(BASE, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function setFeedbackHandled(
  id: string,
  isHandled: boolean,
): Promise<ActionResult<Feedback>> {
  return actionFetch<Feedback>(`${BASE}/${id}/handled`, {
    method: 'PATCH',
    body: JSON.stringify({ is_handled: isHandled }),
  })
}

export async function uploadFeedbackAttachment(
  feedbackId: string,
  formData: FormData,
): Promise<ActionResult<FeedbackAttachment>> {
  try {
    const authHeaders = await getAuthHeaders()
    // 绝不能手工设置 multipart Content-Type，边界由 fetch 自动生成。
    const headers = { ...authHeaders }
    delete headers['Content-Type']
    const response = await fetch(`${BASE}/${feedbackId}/attachments`, {
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
    return { success: true, data: ((json as { data?: FeedbackAttachment } | null)?.data ?? null) }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : '网络错误' }
  }
}

export async function deleteFeedbackAttachment(
  feedbackId: string,
  attachmentId: string,
): Promise<ActionResult> {
  return actionFetch(`${BASE}/${feedbackId}/attachments/${attachmentId}`, { method: 'DELETE' })
}
