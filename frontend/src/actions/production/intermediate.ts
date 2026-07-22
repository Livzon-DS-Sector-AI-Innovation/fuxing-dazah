'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  CreateIntermediateTypeInput,
  IntermediateConsumption,
  IntermediateOutput,
  IntermediateTrace,
  IntermediateType,
  UpdateIntermediateTypeInput,
} from '@/types/production'

const BASE = `${API_BASE}/production`
const MATERIALS_PATH = '/production/materials'

// ── 中间体字典 CRUD ──

export async function createIntermediateType(
  input: CreateIntermediateTypeInput,
): Promise<ActionResult<IntermediateType>> {
  const result = await actionFetch<IntermediateType>(`${BASE}/intermediate-types`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath(MATERIALS_PATH)
  return result
}

export async function updateIntermediateType(
  id: string,
  input: UpdateIntermediateTypeInput,
): Promise<ActionResult<IntermediateType>> {
  const result = await actionFetch<IntermediateType>(
    `${BASE}/intermediate-types/${id}`,
    { method: 'PUT', body: JSON.stringify(input) },
  )
  if (result.success) revalidatePath(MATERIALS_PATH)
  return result
}

export async function deleteIntermediateType(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/intermediate-types/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath(MATERIALS_PATH)
  return result
}

// ── 批次中间体查询 ──

export async function fetchAvailableOutputs(
  intermediateTypeId?: string,
): Promise<ActionResult<IntermediateOutput[]>> {
  const params = intermediateTypeId
    ? `?intermediate_type_id=${encodeURIComponent(intermediateTypeId)}`
    : ''
  return actionFetch<IntermediateOutput[]>(
    `${BASE}/intermediates/available-outputs${params}`,
  )
}

export async function fetchBatchOutputs(
  batchId: string,
): Promise<ActionResult<IntermediateOutput[]>> {
  return actionFetch<IntermediateOutput[]>(
    `${BASE}/batches/${batchId}/intermediates/outputs`,
  )
}

export async function fetchBatchConsumptions(
  batchId: string,
): Promise<ActionResult<IntermediateConsumption[]>> {
  return actionFetch<IntermediateConsumption[]>(
    `${BASE}/batches/${batchId}/intermediates/consumptions`,
  )
}

// ── 溯源 ──

export async function fetchIntermediateTrace(
  outputId: string,
): Promise<ActionResult<IntermediateTrace>> {
  return actionFetch<IntermediateTrace>(
    `${BASE}/intermediates/outputs/${outputId}/trace`,
  )
}

