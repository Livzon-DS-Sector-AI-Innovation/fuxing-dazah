'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type {
  QaDocument,
  QaDocumentMasterLink,
  QaDocumentType,
  QaDocumentVersion,
  QaMasterObject,
} from '@/types/qa'

const BASE = `${API_BASE}/qa`

async function multipartFetch<T = unknown>(url: string, formData: FormData): Promise<ActionResult<T>> {
  try {
    const authHeaders = await getAuthHeaders()
    // 绝不能手工设置 multipart Content-Type，边界由 fetch 自动生成。
    const headers = { ...authHeaders }
    delete headers['Content-Type']
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
    })
    const text = await response.text().catch(() => '')
    let json: unknown = null
    try { json = text ? JSON.parse(text) : null } catch { /* ignore malformed error */ }
    if (!response.ok) {
      const body = json as { message?: string; detail?: string } | null
      return {
        success: false,
        error: body?.message || body?.detail || `请求失败: ${response.status}`,
      }
    }
    return { success: true, data: ((json as { data?: T } | null)?.data ?? json) as T | null }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : '网络错误' }
  }
}

export async function createQaMasterObject(input: Record<string, unknown>): Promise<ActionResult<QaMasterObject>> {
  const result = await actionFetch<QaMasterObject>(`${BASE}/master-objects`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/master-data')
  return result
}

export async function updateQaMasterObject(id: string, input: Record<string, unknown>): Promise<ActionResult<QaMasterObject>> {
  const result = await actionFetch<QaMasterObject>(`${BASE}/master-objects/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/master-data')
  return result
}

export async function setQaMasterObjectActive(id: string, active: boolean): Promise<ActionResult<QaMasterObject>> {
  const path = active ? 'activate' : 'deactivate'
  const result = await actionFetch<QaMasterObject>(`${BASE}/master-objects/${id}/${path}`, { method: 'POST' })
  if (result.success) revalidatePath('/qa/master-data')
  return result
}

export async function updateQaMasterAliases(id: string, aliases: string[]): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/master-objects/${id}/aliases`, {
    method: 'PUT',
    body: JSON.stringify({ aliases }),
  })
  if (result.success) revalidatePath('/qa/master-data')
  return result
}

export async function updateQaMasterSources(id: string, sources: Array<{ source_module: string; source_entity: string; source_id: string }>): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/master-objects/${id}/sources`, {
    method: 'PUT',
    body: JSON.stringify({ sources }),
  })
  if (result.success) revalidatePath('/qa/master-data')
  return result
}

export async function createQaDocument(input: Record<string, unknown>): Promise<ActionResult<QaDocument>> {
  const result = await actionFetch<QaDocument>(`${BASE}/documents`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function updateQaDocument(id: string, input: Record<string, unknown>): Promise<ActionResult<QaDocument>> {
  const result = await actionFetch<QaDocument>(`${BASE}/documents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function setQaDocumentActive(id: string, active: boolean): Promise<ActionResult<QaDocument>> {
  const path = active ? 'activate' : 'deactivate'
  const result = await actionFetch<QaDocument>(`${BASE}/documents/${id}/${path}`, { method: 'POST' })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function uploadQaVersion(
  documentId: string,
  formData: FormData,
): Promise<ActionResult<QaDocumentVersion>> {
  const result = await multipartFetch<QaDocumentVersion>(`${BASE}/documents/${documentId}/versions`, formData)
  if (result.success) {
    revalidatePath('/qa/documents')
    revalidatePath(`/qa/documents/${documentId}`)
  }
  return result
}

export async function updateQaVersionRelations(
  versionId: string,
  masterObjectIds: string[],
): Promise<ActionResult<QaDocumentMasterLink[]>> {
  const result = await actionFetch<QaDocumentMasterLink[]>(`${BASE}/document-versions/${versionId}/relations`, {
    method: 'PUT',
    body: JSON.stringify({ master_object_ids: masterObjectIds }),
  })
  if (result.success) {
    revalidatePath('/qa/documents')
    revalidatePath('/qa')
  }
  return result
}

export async function makeQaVersionCurrent(documentId: string, versionId: string): Promise<ActionResult<QaDocument>> {
  const result = await actionFetch<QaDocument>(`${BASE}/documents/${documentId}/versions/${versionId}/make-current`, {
    method: 'POST',
  })
  if (result.success) {
    revalidatePath('/qa/documents')
    revalidatePath(`/qa/documents/${documentId}`)
    revalidatePath('/qa')
  }
  return result
}

export async function copyQaVersionRelations(documentId: string, versionId: string): Promise<ActionResult<QaDocumentMasterLink[]>> {
  const result = await actionFetch<QaDocumentMasterLink[]>(`${BASE}/documents/${documentId}/versions/${versionId}/copy-relations`, {
    method: 'POST',
  })
  if (result.success) {
    revalidatePath('/qa/documents')
    revalidatePath(`/qa/documents/${documentId}`)
  }
  return result
}

export async function setQaVersionActive(versionId: string, active: boolean): Promise<ActionResult<QaDocumentVersion>> {
  const path = active ? 'activate' : 'deactivate'
  const result = await actionFetch<QaDocumentVersion>(`${BASE}/document-versions/${versionId}/${path}`, {
    method: 'POST',
  })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function retryQaExtraction(fileId: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/document-files/${fileId}/retry`, { method: 'POST' })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function createQaDocumentType(input: Record<string, unknown>): Promise<ActionResult<QaDocumentType>> {
  const result = await actionFetch<QaDocumentType>(`${BASE}/document-types`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function updateQaDocumentType(id: string, input: Record<string, unknown>): Promise<ActionResult<QaDocumentType>> {
  const result = await actionFetch<QaDocumentType>(`${BASE}/document-types/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/qa/documents')
  return result
}

export async function setQaDocumentTypeActive(id: string, active: boolean): Promise<ActionResult<QaDocumentType>> {
  const path = active ? 'activate' : 'deactivate'
  const result = await actionFetch<QaDocumentType>(`${BASE}/document-types/${id}/${path}`, { method: 'POST' })
  if (result.success) revalidatePath('/qa/documents')
  return result
}
