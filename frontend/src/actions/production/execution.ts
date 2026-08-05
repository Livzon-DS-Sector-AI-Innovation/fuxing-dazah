'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  CompleteExecutionInput,
  Execution,
  FieldValue,
  FieldValueInput,
  StartExecutionInput,
} from '@/types/production'

export async function startExecution(
  batchId: string,
  input: StartExecutionInput,
): Promise<ActionResult<Execution>> {
  const result = await actionFetch<Execution>(
    `${API_BASE}/production/batches/${batchId}/executions`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function completeExecution(
  executionId: string,
  input: CompleteExecutionInput,
): Promise<ActionResult<Execution>> {
  const result = await actionFetch<Execution>(
    `${API_BASE}/production/executions/${executionId}/complete`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function backfillExecutionFields(
  executionId: string,
  fieldValues: FieldValueInput[],
): Promise<ActionResult<FieldValue[]>> {
  const result = await actionFetch<FieldValue[]>(
    `${API_BASE}/production/executions/${executionId}/field-values`,
    { method: 'POST', body: JSON.stringify({ field_values: fieldValues }) },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}

export async function abortExecution(executionId: string): Promise<ActionResult<Execution>> {
  const result = await actionFetch<Execution>(
    `${API_BASE}/production/executions/${executionId}/abort`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/batches')
  return result
}
