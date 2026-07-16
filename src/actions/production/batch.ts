'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  CreateBatchInput,
  DeriveInput,
  MergeInput,
  ProductionBatch,
} from '@/types/production'

export async function createBatch(input: CreateBatchInput): Promise<ActionResult<ProductionBatch>> {
  const result = await actionFetch<ProductionBatch>(`${API_BASE}/production/batches`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function deriveBatches(
  batchId: string,
  input: DeriveInput,
): Promise<ActionResult<ProductionBatch[]>> {
  const result = await actionFetch<ProductionBatch[]>(
    `${API_BASE}/production/batches/${batchId}/derive`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function mergeBatches(input: MergeInput): Promise<ActionResult<ProductionBatch>> {
  const result = await actionFetch<ProductionBatch>(`${API_BASE}/production/batches/merge`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function completeBatch(batchId: string): Promise<ActionResult<ProductionBatch>> {
  const result = await actionFetch<ProductionBatch>(
    `${API_BASE}/production/batches/${batchId}/complete`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function cancelBatch(batchId: string): Promise<ActionResult<ProductionBatch>> {
  const result = await actionFetch<ProductionBatch>(
    `${API_BASE}/production/batches/${batchId}/cancel`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}
