'use server'

import '@/lib/http-server'
import { revalidatePath } from 'next/cache'
import { apiGet, apiPatch, apiPost } from '@/lib/http-client'

const SERVER_API =
  process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const BASE = '/api/v1/warehouse/agent'

export interface WebRecognizeResult {
  draft_id: string
  draft_no: string
  status: string
  scene: string
  recognized: Record<string, { value?: string | number | null; confidence?: number | null }>
  aligned: Record<string, unknown>
}

export interface WebDraftDetail {
  draft_id: string
  draft_no: string
  status: string
  scene: string
  source_image: string | null
  recognized: Record<string, { value?: string | number | null; confidence?: number | null }>
  aligned: Record<string, unknown>
}

/** 确认页表单直改 payload：标量字段 + 成品多行行集（可选整体替换） */
export interface WebDraftFieldsUpdate {
  fields?: Record<string, string | number | null>
  rows?: Array<Record<string, string | number | null>>
}

export async function webRecognizeReceipt(
  uploadId: string,
): Promise<WebRecognizeResult> {
  const result = await apiPost<WebRecognizeResult>(
    `${SERVER_API}${BASE}/recognition`,
    { upload_id: uploadId },
  )
  revalidatePath('/warehouse/quick-register')
  return result
}

/** 确认页表单直改（写 aligned working set，与飞书对话修改同一取值口径） */
export async function webUpdateDraftFields(
  draftId: string,
  payload: WebDraftFieldsUpdate,
): Promise<WebDraftDetail> {
  const result = await apiPatch<WebDraftDetail>(
    `${SERVER_API}${BASE}/drafts/${encodeURIComponent(draftId)}/fields`,
    payload,
  )
  revalidatePath('/warehouse/quick-register')
  return result
}

export async function fetchWebDraftDetail(
  draftId: string,
): Promise<WebDraftDetail> {
  return apiGet<WebDraftDetail>(`${SERVER_API}${BASE}/drafts/${encodeURIComponent(draftId)}`)
}

export async function webConfirmDraft(
  draftId: string,
  action: 'confirm' | 'cancel',
): Promise<{ ok: boolean; status: string; draft_status: string | null }> {
  const result = await apiPost<{ ok: boolean; status: string; draft_status: string | null }>(
    `${SERVER_API}${BASE}/drafts/${encodeURIComponent(draftId)}/confirm`,
    { action },
  )
  revalidatePath('/warehouse/quick-register')
  revalidatePath('/warehouse/inventory')
  return result
}
