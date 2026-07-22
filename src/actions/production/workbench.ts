'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  WorkbenchData,
  StageAssignment,
  NodeAssignment,
  ReceiveAndStartInput,
  ReceiveAndStartResult,
} from '@/types/production'

export async function fetchWorkbench(): Promise<ActionResult<WorkbenchData>> {
  const result = await actionFetch<WorkbenchData>(`${API_BASE}/production/workbench`, {
    method: 'GET',
  })
  if (result.success) revalidatePath('/production/workbench')
  return result
}

export async function fetchStageAssignments(routeId: string): Promise<ActionResult<StageAssignment[]>> {
  const result = await actionFetch<StageAssignment[]>(
    `${API_BASE}/production/stage-assignments?route_id=${routeId}`,
    { method: 'GET' },
  )
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function createStageAssignment(
  data: { user_id: string; stage_name: string; route_id: string },
): Promise<ActionResult<StageAssignment>> {
  const result = await actionFetch<StageAssignment>(`${API_BASE}/production/stage-assignments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function deleteStageAssignment(id: string): Promise<ActionResult<null>> {
  const result = await actionFetch<null>(`${API_BASE}/production/stage-assignments/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function fetchNodeAssignments(
  routeId: string, nodeId?: string,
): Promise<ActionResult<NodeAssignment[]>> {
  let url = `${API_BASE}/production/node-assignments?route_id=${routeId}`
  if (nodeId) url += `&node_id=${nodeId}`
  const result = await actionFetch<NodeAssignment[]>(url, { method: 'GET' })
  if (result.success) revalidatePath('/production/workbench')
  return result
}

export async function createNodeAssignment(
  data: { user_id: string; node_id: string; route_id: string },
): Promise<ActionResult<NodeAssignment>> {
  const result = await actionFetch<NodeAssignment>(`${API_BASE}/production/node-assignments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/production/workbench')
  return result
}

export async function deleteNodeAssignment(id: string): Promise<ActionResult<null>> {
  const result = await actionFetch<null>(`${API_BASE}/production/node-assignments/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/production/workbench')
  return result
}

export async function receiveAndStart(
  data: ReceiveAndStartInput,
): Promise<ActionResult<ReceiveAndStartResult>> {
  const result = await actionFetch<ReceiveAndStartResult>(
    `${API_BASE}/production/workbench/receive-and-start`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  if (result.success) revalidatePath('/production/workbench')
  return result
}
