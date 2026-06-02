'use server'

import { revalidatePath } from 'next/cache'
import type {
  Accident,
  AccidentFormData,
  AccidentQueryParams,
  HazardReport,
  HazardReportFormData,
  HazardReportQueryParams,
  SafetyCheck,
  SafetyCheckFormData,
  SafetyCheckQueryParams,
  SafetyTraining,
  SafetyTrainingFormData,
  SafetyTrainingQueryParams,
  TrainingRecord,
  TrainingRecordFormData,
  ApiResponse,
} from '@/types/safety'

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

// ============ SafetyCheck Actions ============

export async function getChecks(params: SafetyCheckQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.check_type) searchParams.set('check_type', params.check_type)
  if (params.department) searchParams.set('department', params.department)

  const queryString = searchParams.toString()
  const endpoint = `/safety/checks${queryString ? `?${queryString}` : ''}`
  return fetchApi<SafetyCheck[]>(endpoint)
}

export async function getCheck(id: string) {
  return fetchApi<SafetyCheck>(`/safety/checks/${id}`)
}

export async function createCheck(data: SafetyCheckFormData) {
  const response = await fetchApi<SafetyCheck>('/safety/checks', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/check')
  return response
}

export async function updateCheck(id: string, data: Partial<SafetyCheckFormData>) {
  const response = await fetchApi<SafetyCheck>(`/safety/checks/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/check')
  return response
}

export async function submitCheck(id: string) {
  const response = await fetchApi<SafetyCheck>(`/safety/checks/${id}/submit`, {
    method: 'POST',
  })
  revalidatePath('/safety/check')
  return response
}

export async function reviewCheck(id: string, result: string) {
  const response = await fetchApi<SafetyCheck>(
    `/safety/checks/${id}/review?result=${result}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/check')
  return response
}

export async function deleteCheck(id: string) {
  const response = await fetchApi<null>(`/safety/checks/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/check')
  return response
}

// ============ HazardReport Actions ============

export async function getHazards(params: HazardReportQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.hazard_type) searchParams.set('hazard_type', params.hazard_type)
  if (params.hazard_level) searchParams.set('hazard_level', params.hazard_level)
  if (params.department) searchParams.set('department', params.department)

  const queryString = searchParams.toString()
  const endpoint = `/safety/hazards${queryString ? `?${queryString}` : ''}`
  return fetchApi<HazardReport[]>(endpoint)
}

export async function getHazard(id: string) {
  return fetchApi<HazardReport>(`/safety/hazards/${id}`)
}

export async function createHazard(data: HazardReportFormData) {
  const response = await fetchApi<HazardReport>('/safety/hazards', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/hazard')
  return response
}

export async function updateHazard(id: string, data: Partial<HazardReportFormData>) {
  const response = await fetchApi<HazardReport>(`/safety/hazards/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/hazard')
  return response
}

export async function startRectification(id: string) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/start`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function completeRectification(id: string) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/complete`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function verifyRectification(id: string, passed: boolean) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/verify?passed=${passed}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function deleteHazard(id: string) {
  const response = await fetchApi<null>(`/safety/hazards/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/hazard')
  return response
}

// ============ Accident Actions ============

export async function getAccidents(params: AccidentQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.accident_type) searchParams.set('accident_type', params.accident_type)
  if (params.accident_level) searchParams.set('accident_level', params.accident_level)

  const queryString = searchParams.toString()
  const endpoint = `/safety/accidents${queryString ? `?${queryString}` : ''}`
  return fetchApi<Accident[]>(endpoint)
}

export async function getAccident(id: string) {
  return fetchApi<Accident>(`/safety/accidents/${id}`)
}

export async function createAccident(data: AccidentFormData) {
  const response = await fetchApi<Accident>('/safety/accidents', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/accident')
  return response
}

export async function updateAccident(id: string, data: Partial<AccidentFormData>) {
  const response = await fetchApi<Accident>(`/safety/accidents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/accident')
  return response
}

export async function investigateAccident(id: string) {
  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/investigate`,
    { method: 'POST' }
  )
  revalidatePath('/safety/accident')
  return response
}

export async function resolveAccident(
  id: string,
  directCause: string,
  rootCause: string,
  handlingMeasures: string,
  correctiveActions?: string
) {
  const params = new URLSearchParams({ direct_cause: directCause, root_cause: rootCause, handling_measures: handlingMeasures })
  if (correctiveActions) params.set('corrective_actions', correctiveActions)

  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/resolve?${params.toString()}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/accident')
  return response
}

export async function closeAccident(id: string) {
  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/close`,
    { method: 'POST' }
  )
  revalidatePath('/safety/accident')
  return response
}

export async function deleteAccident(id: string) {
  const response = await fetchApi<null>(`/safety/accidents/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/accident')
  return response
}

// ============ SafetyTraining Actions ============

export async function getTrainings(params: SafetyTrainingQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.training_type) searchParams.set('training_type', params.training_type)
  if (params.department) searchParams.set('department', params.department)

  const queryString = searchParams.toString()
  const endpoint = `/safety/trainings${queryString ? `?${queryString}` : ''}`
  return fetchApi<SafetyTraining[]>(endpoint)
}

export async function getTraining(id: string) {
  return fetchApi<SafetyTraining>(`/safety/trainings/${id}`)
}

export async function createTraining(data: SafetyTrainingFormData) {
  const response = await fetchApi<SafetyTraining>('/safety/trainings', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/training')
  return response
}

export async function updateTraining(id: string, data: Partial<SafetyTrainingFormData>) {
  const response = await fetchApi<SafetyTraining>(`/safety/trainings/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/training')
  return response
}

export async function startTraining(id: string) {
  const response = await fetchApi<SafetyTraining>(
    `/safety/trainings/${id}/start`,
    { method: 'POST' }
  )
  revalidatePath('/safety/training')
  return response
}

export async function completeTraining(id: string) {
  const response = await fetchApi<SafetyTraining>(
    `/safety/trainings/${id}/complete`,
    { method: 'POST' }
  )
  revalidatePath('/safety/training')
  return response
}

export async function deleteTraining(id: string) {
  const response = await fetchApi<null>(`/safety/trainings/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/training')
  return response
}

// ============ TrainingRecord Actions ============

export async function getTrainingRecords(trainingId: string) {
  return fetchApi<TrainingRecord[]>(`/safety/trainings/${trainingId}/records`)
}

export async function createTrainingRecord(trainingId: string, data: TrainingRecordFormData) {
  const response = await fetchApi<TrainingRecord>(
    `/safety/trainings/${trainingId}/records`,
    {
      method: 'POST',
      body: JSON.stringify({ ...data, training_id: trainingId }),
    }
  )
  revalidatePath(`/safety/training`)
  return response
}

export async function updateTrainingRecord(recordId: string, data: Partial<TrainingRecordFormData>) {
  const response = await fetchApi<TrainingRecord>(
    `/safety/training-records/${recordId}`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
    }
  )
  revalidatePath('/safety/training')
  return response
}

export async function deleteTrainingRecord(recordId: string) {
  const response = await fetchApi<null>(
    `/safety/training-records/${recordId}`,
    { method: 'DELETE' }
  )
  revalidatePath('/safety/training')
  return response
}

// ============ Enum Actions ============

export async function getSafetyEnums() {
  return fetchApi<Record<string, Array<{ value: string; label: string }>>>('/safety/enums')
}
