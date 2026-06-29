'use server'

import { revalidatePath } from 'next/cache'
import { getServerToken } from '@/lib/auth'
import type {
  WorkflowDefCreate,
  WorkflowDefResponse,
  WorkflowDefUpdate,
  WorkflowRunRequest,
  WorkflowRunResponse,
} from '@/types/safety'

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

async function fetchApi<T>(
  path: string,
  options: RequestInit = {},
): Promise<{ code: number; message: string; data: T; meta?: Record<string, unknown> }> {
  const token = await getServerToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const res = await fetch(`${API_BASE}/api/v1${path}`, { ...options, headers })
  if (!res.ok) {
    throw new Error(`API Error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

// ============ Workflow Definitions ============

export async function listWorkflowDefinitions(params?: {
  page?: number
  page_size?: number
  module_code?: string
  is_enabled?: boolean
}): Promise<{ data: WorkflowDefResponse[]; meta: { page: number; page_size: number; total: number } }> {
  const searchParams = new URLSearchParams()
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  if (params?.module_code) searchParams.set('module_code', params.module_code)
  if (params?.is_enabled !== undefined) searchParams.set('is_enabled', String(params.is_enabled))
  const qs = searchParams.toString()
  const result = await fetchApi<WorkflowDefResponse[]>(
    `/safety/workflow/definitions${qs ? `?${qs}` : ''}`,
  )
  return { data: result.data, meta: result.meta as { page: number; page_size: number; total: number } }
}

export async function getWorkflowDefinition(id: string) {
  const result = await fetchApi<WorkflowDefResponse>(`/safety/workflow/definitions/${id}`)
  return result
}

export async function createWorkflowDefinition(data: WorkflowDefCreate) {
  const result = await fetchApi<WorkflowDefResponse>('/safety/workflow/definitions', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/workflow')
  return result
}

export async function updateWorkflowDefinition(id: string, data: WorkflowDefUpdate) {
  const result = await fetchApi<WorkflowDefResponse>(`/safety/workflow/definitions/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/workflow')
  revalidatePath(`/safety/workflow/${id}`)
  return result
}

export async function deleteWorkflowDefinition(id: string) {
  const result = await fetchApi<null>(`/safety/workflow/definitions/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/workflow')
  return result
}

// ============ Workflow Runs ============

export async function runWorkflow(id: string, body: WorkflowRunRequest) {
  const result = await fetchApi<WorkflowRunResponse>(`/safety/workflow/definitions/${id}/run`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return result
}

export async function listWorkflowRuns(params?: {
  page?: number
  page_size?: number
  workflow_id?: string
}): Promise<{ data: WorkflowRunResponse[]; meta: { page: number; page_size: number; total: number } }> {
  const searchParams = new URLSearchParams()
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))
  if (params?.workflow_id) searchParams.set('workflow_id', params.workflow_id)
  const qs = searchParams.toString()
  const result = await fetchApi<WorkflowRunResponse[]>(
    `/safety/workflow/runs${qs ? `?${qs}` : ''}`,
  )
  return { data: result.data, meta: result.meta as { page: number; page_size: number; total: number } }
}

export async function getWorkflowRun(id: string) {
  const result = await fetchApi<WorkflowRunResponse>(`/safety/workflow/runs/${id}`)
  return result
}
