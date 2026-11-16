'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type {
  CoaItemInput,
  CoaProduct,
  CoaProductInput,
  CoaReport,
  CoaReportInput,
  CoaStandard,
  CoaStandardInput,
} from '@/types/qa'

const BASE = `${API_BASE}/qa/coa`

function revalidateCoa() {
  revalidatePath('/qa/coa/standards')
  revalidatePath('/qa/coa/issuance')
}

// ───────────────────────── 产品 ─────────────────────────

export async function createCoaProduct(input: CoaProductInput): Promise<ActionResult<CoaProduct>> {
  const result = await actionFetch<CoaProduct>(`${BASE}/products`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

export async function updateCoaProduct(
  id: string,
  input: Partial<CoaProductInput>
): Promise<ActionResult<CoaProduct>> {
  const result = await actionFetch<CoaProduct>(`${BASE}/products/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

// ───────────────────────── 客户标准 ─────────────────────────

export async function createCoaStandard(
  input: CoaStandardInput
): Promise<ActionResult<CoaStandard>> {
  const result = await actionFetch<CoaStandard>(`${BASE}/standards`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

export async function updateCoaStandard(
  id: string,
  input: Partial<Omit<CoaStandardInput, 'items' | 'raw_extract'>>
): Promise<ActionResult<CoaStandard>> {
  const result = await actionFetch<CoaStandard>(`${BASE}/standards/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

export async function deleteCoaStandard(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/standards/${id}`, { method: 'DELETE' })
  if (result.success) revalidateCoa()
  return result
}

/** 标准项目全量替换（不在载荷中的按引用守卫停用/软删）。 */
export async function replaceCoaStandardItems(
  standardId: string,
  items: CoaItemInput[]
): Promise<ActionResult<CoaStandard>> {
  const result = await actionFetch<CoaStandard>(`${BASE}/standards/${standardId}/items`, {
    method: 'PUT',
    body: JSON.stringify({ items }),
  })
  if (result.success) revalidateCoa()
  return result
}

// ───────────────────────── 出具登记 ─────────────────────────

export async function createCoaReport(input: CoaReportInput): Promise<ActionResult<CoaReport>> {
  const result = await actionFetch<CoaReport>(`${BASE}/reports`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

export async function updateCoaReport(
  id: string,
  input: Partial<CoaReportInput>
): Promise<ActionResult<CoaReport>> {
  const result = await actionFetch<CoaReport>(`${BASE}/reports/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}

export async function deleteCoaReport(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/reports/${id}`, { method: 'DELETE' })
  if (result.success) revalidateCoa()
  return result
}
