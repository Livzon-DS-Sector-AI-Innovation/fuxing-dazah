// 快速登记 API（分期B Ticket 08）：上传走 multipart（cookie 鉴权），识别/确认走 Server Actions
export interface QuickRegisterDraft {
  draft_id: string
  draft_no: string
  status: string
  recognized: Record<string, { value?: string | number | null; confidence?: number | null }>
  aligned: Record<string, unknown>
}

export async function uploadReceiptImage(file: File): Promise<{ upload_id: string }> {
  const form = new FormData()
  form.append('file', file)
  const resp = await fetch('/api/v1/warehouse/agent/uploads', {
    method: 'POST',
    body: form,
  })
  const body = await resp.json().catch(() => null)
  if (!resp.ok) {
    throw new Error(body?.message ?? `上传失败（${resp.status}）`)
  }
  return body.data as { upload_id: string }
}

export async function fetchDraftImageBlobUrl(uploadId: string): Promise<string> {
  const resp = await fetch(`/api/v1/warehouse/agent/uploads/${encodeURIComponent(uploadId)}`)
  if (!resp.ok) throw new Error(`图片加载失败（${resp.status}）`)
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}
