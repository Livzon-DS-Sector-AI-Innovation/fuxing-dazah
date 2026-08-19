'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  Line,
  LineAssignment,
  LineAssignmentCreateInput,
  LineCreateInput,
  LineUpdateInput,
} from '@/types/production'

const BASE = `${API_BASE}/production`
const MASTER_DATA_PATH = '/production/master-data'

// ── 产线字典 CRUD ──

export async function fetchLines(): Promise<ActionResult<Line[]>> {
  return actionFetch<Line[]>(`${BASE}/lines`)
}

export async function createLine(
  input: LineCreateInput,
): Promise<ActionResult<Line>> {
  const result = await actionFetch<Line>(`${BASE}/lines`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath(MASTER_DATA_PATH)
  return result
}

export async function updateLine(
  id: string,
  input: LineUpdateInput,
): Promise<ActionResult<Line>> {
  const result = await actionFetch<Line>(`${BASE}/lines/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath(MASTER_DATA_PATH)
  return result
}

export async function deleteLine(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${BASE}/lines/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath(MASTER_DATA_PATH)
  return result
}

// ── 用户-产线绑定 ──

export async function fetchMyLineAssignments(): Promise<
  ActionResult<LineAssignment[]>
> {
  return actionFetch<LineAssignment[]>(`${BASE}/line-assignments`)
}

export async function fetchLineAssignments(
  lineId: string,
): Promise<ActionResult<LineAssignment[]>> {
  return actionFetch<LineAssignment[]>(
    `${BASE}/line-assignments?line_id=${encodeURIComponent(lineId)}`,
  )
}

export async function fetchLineAssignmentsByUser(
  userId: string,
): Promise<ActionResult<LineAssignment[]>> {
  return actionFetch<LineAssignment[]>(
    `${BASE}/line-assignments?user_id=${encodeURIComponent(userId)}`,
  )
}

export async function bindLineAssignment(
  input: LineAssignmentCreateInput,
): Promise<ActionResult<LineAssignment>> {
  const result = await actionFetch<LineAssignment>(`${BASE}/line-assignments`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath(MASTER_DATA_PATH)
  return result
}

export async function unbindLineAssignment(
  assignmentId: string,
): Promise<ActionResult> {
  const result = await actionFetch(
    `${BASE}/line-assignments/${assignmentId}`,
    { method: 'DELETE' },
  )
  if (result.success) revalidatePath(MASTER_DATA_PATH)
  return result
}
