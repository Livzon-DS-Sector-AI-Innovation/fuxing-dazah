'use server'

import { revalidatePath } from 'next/cache'
import type {
  Batch,
  BatchMaterial,
  ProductionPlan,
  PlanTask,
  ProcessSpec,
  ProcessStep,
  ProcessParameter,
  ProductionRecord,
  MaterialBalance,
  BatchFormData,
  BatchMaterialFormData,
  ProductionPlanFormData,
  PlanTaskFormData,
  ProcessSpecFormData,
  ProcessStepFormData,
  ProcessParameterFormData,
  ProductionRecordFormData,
  BatchQueryParams,
  PlanQueryParams,
  ProcessSpecQueryParams,
  ApiResponse,
} from '@/types/production'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

// ============ Helper Functions ============

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  })
  return response.json()
}

// ============ Batch Actions ============

export async function getBatches(params: BatchQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.product_code) searchParams.set('product_code', params.product_code)
  if (params.batch_no) searchParams.set('batch_no', params.batch_no)

  const queryString = searchParams.toString()
  const endpoint = `/production/batches${queryString ? `?${queryString}` : ''}`
  return fetchApi<Batch[]>(endpoint)
}

export async function getBatch(id: string) {
  return fetchApi<Batch>(`/production/batches/${id}`)
}

export async function createBatch(data: BatchFormData) {
  const response = await fetchApi<Batch>('/production/batches', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/batches')
  return response
}

export async function updateBatch(id: string, data: Partial<BatchFormData>) {
  const response = await fetchApi<Batch>(`/production/batches/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/batches')
  return response
}

export async function updateBatchStatus(id: string, status: string) {
  const response = await fetchApi<Batch>(`/production/batches/${id}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })
  revalidatePath('/production/batches')
  return response
}

export async function deleteBatch(id: string) {
  const response = await fetchApi<null>(`/production/batches/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/production/batches')
  return response
}

// ============ Batch Material Actions ============

export async function getBatchMaterials(batchId: string) {
  return fetchApi<BatchMaterial[]>(`/production/batches/${batchId}/materials`)
}

export async function addBatchMaterial(batchId: string, data: BatchMaterialFormData) {
  const response = await fetchApi<BatchMaterial>(`/production/batches/${batchId}/materials`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath(`/production/batches/${batchId}`)
  return response
}

export async function updateBatchMaterial(id: string, data: Partial<BatchMaterialFormData>) {
  return fetchApi<BatchMaterial>(`/production/materials/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteBatchMaterial(id: string) {
  return fetchApi<null>(`/production/materials/${id}`, {
    method: 'DELETE',
  })
}

// ============ Production Plan Actions ============

export async function getPlans(params: PlanQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.plan_month) searchParams.set('plan_month', params.plan_month)

  const queryString = searchParams.toString()
  const endpoint = `/production/plans${queryString ? `?${queryString}` : ''}`
  return fetchApi<ProductionPlan[]>(endpoint)
}

export async function getPlan(id: string) {
  return fetchApi<ProductionPlan>(`/production/plans/${id}`)
}

export async function createPlan(data: ProductionPlanFormData) {
  const response = await fetchApi<ProductionPlan>('/production/plans', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/plan')
  return response
}

export async function updatePlan(id: string, data: Partial<ProductionPlanFormData>) {
  const response = await fetchApi<ProductionPlan>(`/production/plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/plan')
  return response
}

export async function deletePlan(id: string) {
  const response = await fetchApi<null>(`/production/plans/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/production/plan')
  return response
}

// ============ Plan Task Actions ============

export async function getPlanTasks(planId: string) {
  return fetchApi<PlanTask[]>(`/production/plans/${planId}/tasks`)
}

export async function createPlanTask(data: PlanTaskFormData & { plan_id: string }) {
  const response = await fetchApi<PlanTask>('/production/tasks', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath(`/production/plan/${data.plan_id}`)
  return response
}

export async function updatePlanTask(id: string, data: Partial<PlanTaskFormData>) {
  return fetchApi<PlanTask>(`/production/tasks/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deletePlanTask(id: string) {
  return fetchApi<null>(`/production/tasks/${id}`, {
    method: 'DELETE',
  })
}

// ============ Process Spec Actions ============

export async function getProcessSpecs(params: ProcessSpecQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.product_code) searchParams.set('product_code', params.product_code)

  const queryString = searchParams.toString()
  const endpoint = `/production/process-specs${queryString ? `?${queryString}` : ''}`
  return fetchApi<ProcessSpec[]>(endpoint)
}

export async function getProcessSpec(id: string) {
  return fetchApi<ProcessSpec>(`/production/process-specs/${id}`)
}

export async function createProcessSpec(data: ProcessSpecFormData) {
  const response = await fetchApi<ProcessSpec>('/production/process-specs', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/process')
  return response
}

export async function updateProcessSpec(id: string, data: Partial<ProcessSpecFormData>) {
  const response = await fetchApi<ProcessSpec>(`/production/process-specs/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/production/process')
  return response
}

export async function deleteProcessSpec(id: string) {
  const response = await fetchApi<null>(`/production/process-specs/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/production/process')
  return response
}

// ============ Process Step Actions ============

export async function getProcessSteps(specId: string) {
  return fetchApi<ProcessStep[]>(`/production/process-specs/${specId}/steps`)
}

export async function createProcessStep(data: ProcessStepFormData & { spec_id: string }) {
  const response = await fetchApi<ProcessStep>('/production/steps', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath(`/production/process/${data.spec_id}`)
  return response
}

export async function updateProcessStep(id: string, data: Partial<ProcessStepFormData>) {
  return fetchApi<ProcessStep>(`/production/steps/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteProcessStep(id: string) {
  return fetchApi<null>(`/production/steps/${id}`, {
    method: 'DELETE',
  })
}

// ============ Process Parameter Actions ============

export async function getProcessParameters(stepId: string) {
  return fetchApi<ProcessParameter[]>(`/production/steps/${stepId}/parameters`)
}

export async function createProcessParameter(data: ProcessParameterFormData & { step_id: string }) {
  const response = await fetchApi<ProcessParameter>('/production/parameters', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath(`/production/process`)
  return response
}

export async function deleteProcessParameter(id: string) {
  return fetchApi<null>(`/production/parameters/${id}`, {
    method: 'DELETE',
  })
}

// ============ Production Record Actions ============

export async function getProductionRecords(batchId: string, page = 1, pageSize = 100) {
  return fetchApi<ProductionRecord[]>(
    `/production/batches/${batchId}/records?page=${page}&page_size=${pageSize}`
  )
}

export async function createProductionRecord(data: ProductionRecordFormData & { batch_id: string }) {
  const response = await fetchApi<ProductionRecord>('/production/records', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath(`/production/records`)
  return response
}

export async function updateProductionRecord(id: string, data: Partial<ProductionRecordFormData>) {
  return fetchApi<ProductionRecord>(`/production/records/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteProductionRecord(id: string) {
  return fetchApi<null>(`/production/records/${id}`, {
    method: 'DELETE',
  })
}

// ============ Material Balance Actions ============

export async function getMaterialBalance(batchId: string) {
  return fetchApi<MaterialBalance>(`/production/batches/${batchId}/balance`)
}

export async function calculateMaterialBalance(batchId: string, minBalanceRate = 95.0) {
  const response = await fetchApi<MaterialBalance>(
    `/production/batches/${batchId}/balance/calculate?min_balance_rate=${minBalanceRate}`,
    { method: 'POST' }
  )
  revalidatePath(`/production/balance`)
  return response
}