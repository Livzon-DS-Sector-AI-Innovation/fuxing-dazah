'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type {
  AprAnnualReview,
  AprBatch,
  AprBatchInput,
  AprBatchValuesPayload,
  AprItem,
  AprItemDraft,
  AprItemInput,
  AprProduct,
  AprProductInput,
  AprSection,
  AprSectionInput,
  AprValueInput,
} from '@/types/qa-apr'

const BASE = `${API_BASE}/qa/apr`

function revalidateApr() {
  revalidatePath('/qa/apr/entry')
  revalidatePath('/qa/apr/summary')
  revalidatePath('/qa/apr/config')
}

// ───────────────────────── 产品 ─────────────────────────

export async function createAprProduct(input: AprProductInput): Promise<ActionResult<AprProduct>> {
  const result = await actionFetch<AprProduct>(`${BASE}/products`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function updateAprProduct(
  id: string,
  input: Partial<AprProductInput>,
): Promise<ActionResult<AprProduct>> {
  const result = await actionFetch<AprProduct>(`${BASE}/products/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function deleteAprProduct(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/products/${id}`, { method: 'DELETE' })
  if (result.success) revalidateApr()
  return result
}

// ───────────────────────── 模板段与列定义 ─────────────────────────

export async function createAprSection(input: AprSectionInput): Promise<ActionResult<AprSection>> {
  const result = await actionFetch<AprSection>(`${BASE}/sections`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function updateAprSection(
  id: string,
  input: Partial<AprSectionInput>,
): Promise<ActionResult<AprSection>> {
  const result = await actionFetch<AprSection>(`${BASE}/sections/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function deleteAprSection(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/sections/${id}`, { method: 'DELETE' })
  if (result.success) revalidateApr()
  return result
}

export async function createAprItem(input: AprItemInput): Promise<ActionResult<AprItem>> {
  const result = await actionFetch<AprItem>(`${BASE}/items`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function createAprItemsBulk(
  sectionId: string,
  items: AprItemDraft[],
): Promise<ActionResult<{ count: number }>> {
  const result = await actionFetch<{ count: number }>(`${BASE}/sections/${sectionId}/items/bulk`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
  if (result.success) revalidateApr()
  return result
}

export async function updateAprItem(
  id: string,
  input: Partial<AprItemInput>,
): Promise<ActionResult<AprItem>> {
  const result = await actionFetch<AprItem>(`${BASE}/items/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function deleteAprItem(id: string): Promise<ActionResult<AprItem>> {
  const result = await actionFetch<AprItem>(`${BASE}/items/${id}`, { method: 'DELETE' })
  if (result.success) revalidateApr()
  return result
}

export async function copyAprTemplate(
  productId: string,
  sourceProductId: string,
): Promise<ActionResult<{ sections: number; items: number }>> {
  const result = await actionFetch<{ sections: number; items: number }>(
    `${BASE}/templates/${productId}/copy-from/${sourceProductId}`,
    { method: 'POST' },
  )
  if (result.success) revalidateApr()
  return result
}

// ───────────────────────── 批次与值 ─────────────────────────

export async function createAprBatch(input: AprBatchInput): Promise<ActionResult<AprBatch>> {
  const result = await actionFetch<AprBatch>(`${BASE}/batches`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function updateAprBatch(
  id: string,
  input: Partial<AprBatchInput>,
): Promise<ActionResult<AprBatch>> {
  const result = await actionFetch<AprBatch>(`${BASE}/batches/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateApr()
  return result
}

export async function deleteAprBatch(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/batches/${id}`, { method: 'DELETE' })
  if (result.success) revalidateApr()
  return result
}

export async function saveAprBatchValues(
  batchId: string,
  values: AprValueInput[],
): Promise<ActionResult<{ batch_id: string; saved: number }>> {
  const result = await actionFetch<{ batch_id: string; saved: number }>(
    `${BASE}/batches/${batchId}/values`,
    { method: 'PUT', body: JSON.stringify({ values }) },
  )
  if (result.success) revalidateApr()
  return result
}

// ───────────────────────── 年度锁定 ─────────────────────────

export async function lockAprYear(
  productId: string,
  year: number,
  locked: boolean,
): Promise<ActionResult<AprAnnualReview>> {
  const result = await actionFetch<AprAnnualReview>(
    `${BASE}/annual-reviews/${productId}/${year}/${locked ? 'lock' : 'unlock'}`,
    { method: 'POST' },
  )
  if (result.success) revalidateApr()
  return result
}

// ───────────────────────── 回读（server 侧供表单初始值） ─────────────────────────

export async function fetchAprBatchValuesForEdit(
  batchId: string,
): Promise<ActionResult<AprBatchValuesPayload>> {
  return actionFetch<AprBatchValuesPayload>(`${BASE}/batches/${batchId}/values`)
}
