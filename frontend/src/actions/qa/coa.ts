'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from '@/actions/production/helpers'
import type {
  CoaCopyReportInput,
  CoaCopyReportResult,
  CoaItemInput,
  CoaProduct,
  CoaProductField,
  CoaProductFieldInput,
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

/** 产品批次信息字段配置全量替换。 */
export async function replaceCoaProductFields(
  productId: string,
  fields: CoaProductFieldInput[]
): Promise<ActionResult<CoaProductField[]>> {
  const result = await actionFetch<CoaProductField[]>(
    `${BASE}/products/${productId}/fields`,
    {
      method: 'PUT',
      body: JSON.stringify({ fields }),
    }
  )
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

/** 标准批次信息字段覆盖全量替换（与产品默认解耦）。 */
export async function replaceCoaStandardFields(
  standardId: string,
  fields: CoaProductFieldInput[]
): Promise<ActionResult<{ batch_fields: CoaProductField[]; batch_fields_custom: boolean }>> {
  const result = await actionFetch<{ batch_fields: CoaProductField[]; batch_fields_custom: boolean }>(
    `${BASE}/standards/${standardId}/fields`,
    {
      method: 'PUT',
      body: JSON.stringify({ fields }),
    }
  )
  if (result.success) revalidateCoa()
  return result
}

/** 恢复产品默认批次信息字段（删标准覆盖）。 */
export async function restoreCoaStandardFields(
  standardId: string
): Promise<ActionResult<{ batch_fields: CoaProductField[]; batch_fields_custom: boolean }>> {
  const result = await actionFetch<{ batch_fields: CoaProductField[]; batch_fields_custom: boolean }>(
    `${BASE}/standards/${standardId}/fields`,
    { method: 'DELETE' }
  )
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

/** 复制到其它模板：把一条记录的若干格登记到同产品另一模板的同批号记录（没有就新建）。 */
export async function copyCoaReport(
  sourceId: string,
  input: CoaCopyReportInput
): Promise<ActionResult<CoaCopyReportResult>> {
  const result = await actionFetch<CoaCopyReportResult>(`${BASE}/reports/${sourceId}/copy`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidateCoa()
  return result
}
