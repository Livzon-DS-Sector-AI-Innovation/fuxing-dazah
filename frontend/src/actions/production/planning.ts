'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  CreateDemandInput,
  UpdateDemandInput,
  Demand,
  CreatePlanOrderInput,
  UpdatePlanOrderInput,
  PlanOrder,
  CreatePlanItemInput,
  UpdatePlanItemInput,
  SchedulePlanItemInput,
  PlanItem,
  CreateDemandAllocationInput,
  DemandAllocation,
} from '@/types/production'

const BASE = `${API_BASE}/production`
const revalidate = () => revalidatePath('/production/planning-center')

// ── Demand ──

export async function createDemand(input: CreateDemandInput): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updateDemand(id: string, input: UpdateDemandInput): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deleteDemand(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/demands/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function confirmDemand(id: string): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}/confirm`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function cancelDemand(id: string): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}/cancel`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

// ── PlanOrder ──

export async function createPlanOrder(input: CreatePlanOrderInput): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updatePlanOrder(id: string, input: UpdatePlanOrderInput): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deletePlanOrder(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/plan-orders/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function confirmPlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/confirm`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function releasePlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/release`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function closePlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/close`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

// ── PlanItem ──

export async function createPlanItem(orderId: string, input: CreatePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-orders/${orderId}/items`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updatePlanItem(id: string, input: UpdatePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-items/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deletePlanItem(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/plan-items/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function schedulePlanItem(id: string, input: SchedulePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-items/${id}/schedule`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

// ── Demand Allocation ──

export async function createDemandAllocation(demandId: string, input: CreateDemandAllocationInput): Promise<ActionResult<DemandAllocation>> {
  const result = await actionFetch<DemandAllocation>(`${BASE}/demands/${demandId}/allocations`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deleteDemandAllocation(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/demand-allocations/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}
