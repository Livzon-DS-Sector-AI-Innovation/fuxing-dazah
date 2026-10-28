'use client'

import { apiFetchPaginated, apiGet } from '@/lib/http-client'
import type { Feedback, FeedbackListParams } from '@/types/feedback'

// 浏览器优先走 Next rewrite，避免跨端口/跨域时 httpOnly auth cookie 丢失；
// 服务端调用再使用显式后端地址（与 lib/api/qa.ts 同口径）。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const BASE = `${API_BASE}/api/v1/feedback`

/** React Query 键：写操作后统一失效 `all` 即可刷新列表与角标。 */
export const feedbackKeys = {
  all: ['feedback'] as const,
  pendingCount: ['feedback', 'pending-count'] as const,
  list: (params: FeedbackListParams) => ['feedback', 'list', params] as const,
  mine: (params: Pick<FeedbackListParams, 'page' | 'page_size'>) =>
    ['feedback', 'mine', params] as const,
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export function fetchFeedbackList(params: FeedbackListParams = {}) {
  return apiFetchPaginated<Feedback>(
    `${BASE}${qs({
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
      is_handled: params.is_handled ?? null,
      type: params.type ?? null,
    })}`,
  )
}

export function fetchMyFeedbacks(params: Pick<FeedbackListParams, 'page' | 'page_size'> = {}) {
  return apiFetchPaginated<Feedback>(
    `${BASE}/mine${qs({ page: params.page ?? 1, page_size: params.page_size ?? 20 })}`,
  )
}

export async function fetchFeedbackPendingCount(): Promise<number> {
  const data = await apiGet<{ pending: number }>(`${BASE}/pending-count`)
  return data.pending
}

/** 截图直连后端读取，靠 auth_token cookie 鉴权（与 QA 偏差附件同法），可直接作 <img src>。 */
export function feedbackAttachmentUrl(feedbackId: string, attachmentId: string): string {
  return `${BASE}/${feedbackId}/attachments/${attachmentId}/content`
}
