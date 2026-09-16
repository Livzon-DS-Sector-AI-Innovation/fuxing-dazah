'use server'

import '@/lib/http-server'
import { revalidatePath } from 'next/cache'
import { apiGet, apiPost } from '@/lib/http-client'

const SERVER_API =
  process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const BASE = '/api/v1/warehouse/agent'

export interface WebRecognizeResult {
  draft_id: string
  draft_no: string
  status: string
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
