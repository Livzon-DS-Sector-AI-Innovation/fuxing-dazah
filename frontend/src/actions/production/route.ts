'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type { CreateRouteInput, ProcessRoute, RouteGraphIn } from '@/types/production'

export async function createRoute(input: CreateRouteInput): Promise<ActionResult<ProcessRoute>> {
  const result = await actionFetch<ProcessRoute>(`${API_BASE}/production/routes`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function saveRouteGraph(
  routeId: string,
  graph: RouteGraphIn,
): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE}/production/routes/${routeId}/graph`, {
    method: 'PUT',
    body: JSON.stringify(graph),
  })
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function publishRoute(routeId: string): Promise<ActionResult<ProcessRoute>> {
  const result = await actionFetch<ProcessRoute>(
    `${API_BASE}/production/routes/${routeId}/publish`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function archiveRoute(routeId: string): Promise<ActionResult<ProcessRoute>> {
  const result = await actionFetch<ProcessRoute>(
    `${API_BASE}/production/routes/${routeId}/archive`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function newRouteVersion(routeId: string): Promise<ActionResult<ProcessRoute>> {
  const result = await actionFetch<ProcessRoute>(
    `${API_BASE}/production/routes/${routeId}/new-version`,
    { method: 'POST' },
  )
  if (result.success) revalidatePath('/production/process')
  return result
}

export async function deleteRoute(routeId: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE}/production/routes/${routeId}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/production/process')
  return result
}
