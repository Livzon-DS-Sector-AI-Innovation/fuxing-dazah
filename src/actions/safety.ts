'use server'

import { revalidatePath } from 'next/cache'
import type {
  Accident,
  AccidentFormData,
  AccidentQueryParams,
  AssignRectificationRequest,
  CompleteRectificationRequest,
  ConfirmCheckRequest,
  Contractor,
  ContractorFormData,
  ContractorQueryParams,
  ContractorWorkRecord,
  ContractorWorkRecordFormData,
  ExtendDeadlineRequest,
  HazardReport,
  HazardReportFormData,
  HazardReportQueryParams,
  HazardRevisionArchive,
  HazardRevisionArchiveFormData,
  HazardRevisionArchiveQueryParams,
  HazardRevisionRecord,
  HazardRevisionRecordFormData,
  HazardRevisionRecordQueryParams,
  OperationRegulation,
  OperationRegulationFormData,
  OperationRegulationQueryParams,
  RegulationRevision,
  RegulationRevisionFormData,
  RegulationRevisionQueryParams,
  SafetyCheck,
  SafetyCheckFormData,
  SafetyCheckQueryParams,
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleFormData,
  SafetyKnowledgeArticleQueryParams,
  SafetyTraining,
  SafetyTrainingFormData,
  SafetyTrainingQueryParams,
  SpecialOperationPermit,
  SpecialOperationPermitFormData,
  SpecialOperationPermitQueryParams,
  SpecialOperationPersonnel,
  SpecialOperationPersonnelFormData,
  SpecialOperationPersonnelQueryParams,
  SpecialOperationReport,
  SpecialOperationReportFormData,
  SpecialOperationReportQueryParams,
  DailyRiskReport,
  DailyRiskReportFormData,
  DailyRiskReportQueryParams,
  TrainingRecord,
  TrainingRecordFormData,
  ApiResponse,
} from '@/types/safety'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8002/api/v1'

// ============ Helper Functions ============

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<ApiResponse<T>> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
      },
      ...options,
    })
  } catch {
    return {
      code: -1,
      message: `网络请求失败，无法连接到后端服务 (${API_BASE}${endpoint})`,
    } as ApiResponse<T>
  }

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`
    try {
      const errorBody = await response.text()
      try {
        const errorJson = JSON.parse(errorBody)
        if (errorJson.message) {
          errorMessage = errorJson.message
        } else if (errorJson.detail) {
          errorMessage = errorJson.detail
        }
      } catch {
        errorMessage = errorBody.substring(0, 200)
      }
    } catch {
      // 无法读取响应体
    }
    return { code: response.status, message: errorMessage } as ApiResponse<T>
  }

  try {
    return await response.json()
  } catch {
    const text = await response.text().catch(() => '无法读取响应')
    return {
      code: -1,
      message: `响应解析失败: ${text.substring(0, 200)}`,
    } as ApiResponse<T>
  }
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
  if (params.hazard_category) searchParams.set('hazard_category', params.hazard_category)
  if (params.department) searchParams.set('department', params.department)
  if (params.keyword) searchParams.set('keyword', params.keyword)

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

export async function completeRectification(id: string, data?: CompleteRectificationRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/complete`,
    { method: 'POST', body: JSON.stringify(data || {}) }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function assignRectification(id: string, data: AssignRectificationRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/assign`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function extendDeadline(id: string, data: ExtendDeadlineRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/extend`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function confirmCheck(id: string, data: ConfirmCheckRequest) {
  const response = await fetchApi<SafetyCheck>(
    `/safety/checks/${id}/confirm`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety')
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
  if (params.department) searchParams.set('department', params.department)
  if (params.date_from) searchParams.set('date_from', params.date_from)
  if (params.date_to) searchParams.set('date_to', params.date_to)
  if (params.keyword) searchParams.set('keyword', params.keyword)

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
  correctiveActions?: string,
  investigationFindings?: string,
  investigationMethod?: string
) {
  const params = new URLSearchParams({ direct_cause: directCause, root_cause: rootCause, handling_measures: handlingMeasures })
  if (correctiveActions) params.set('corrective_actions', correctiveActions)
  if (investigationFindings) params.set('investigation_findings', investigationFindings)
  if (investigationMethod) params.set('investigation_method', investigationMethod)

  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/resolve?${params.toString()}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/accident')
  return response
}

export async function startCapa(
  id: string,
  deadline: string,
  responsible: string
) {
  const params = new URLSearchParams({ corrective_action_deadline: deadline, corrective_action_responsible: responsible })
  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/start-capa?${params.toString()}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/accident')
  return response
}

export async function verifyCapa(id: string) {
  const response = await fetchApi<Accident>(
    `/safety/accidents/${id}/verify-capa`,
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

// ============ Contractor Actions ============

export async function getContractors(params: ContractorQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.qualification_type) searchParams.set('qualification_type', params.qualification_type)
  if (params.training_status) searchParams.set('training_status', params.training_status)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/contractors${queryString ? `?${queryString}` : ''}`
  return fetchApi<Contractor[]>(endpoint)
}

export async function getContractor(id: string) {
  return fetchApi<Contractor>(`/safety/contractors/${id}`)
}

export async function createContractor(data: ContractorFormData) {
  const response = await fetchApi<Contractor>('/safety/contractors', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/contractor')
  return response
}

export async function updateContractor(id: string, data: Partial<ContractorFormData>) {
  const response = await fetchApi<Contractor>(`/safety/contractors/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/contractor')
  return response
}

export async function deleteContractor(id: string) {
  const response = await fetchApi<null>(`/safety/contractors/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/contractor')
  return response
}

export async function blacklistContractor(id: string) {
  const response = await fetchApi<Contractor>(`/safety/contractors/${id}/blacklist`, { method: 'POST' })
  revalidatePath('/safety/contractor')
  return response
}

export async function activateContractor(id: string) {
  const response = await fetchApi<Contractor>(`/safety/contractors/${id}/activate`, { method: 'POST' })
  revalidatePath('/safety/contractor')
  return response
}

export async function updateContractorTraining(id: string, trainingStatus: string) {
  const params = new URLSearchParams({ training_status: trainingStatus })
  const response = await fetchApi<Contractor>(
    `/safety/contractors/${id}/update-training?${params.toString()}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/contractor')
  return response
}

export async function getWorkRecords(contractorId: string) {
  return fetchApi<ContractorWorkRecord[]>(`/safety/contractors/${contractorId}/work-records`)
}

export async function createWorkRecord(contractorId: string, data: ContractorWorkRecordFormData) {
  const response = await fetchApi<ContractorWorkRecord>(
    `/safety/contractors/${contractorId}/work-records`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/contractor')
  return response
}

export async function updateWorkRecord(
  contractorId: string, recordId: string, data: Partial<ContractorWorkRecordFormData>
) {
  const response = await fetchApi<ContractorWorkRecord>(
    `/safety/contractors/${contractorId}/work-records/${recordId}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/contractor')
  return response
}

export async function deleteWorkRecord(contractorId: string, recordId: string) {
  const response = await fetchApi<null>(
    `/safety/contractors/${contractorId}/work-records/${recordId}`,
    { method: 'DELETE' }
  )
  revalidatePath('/safety/contractor')
  return response
}

export async function evaluateWorkRecord(
  contractorId: string, recordId: string, score: number, comments?: string, evaluator?: string
) {
  const response = await fetchApi<ContractorWorkRecord>(
    `/safety/contractors/${contractorId}/work-records/${recordId}/evaluate`,
    { method: 'POST', body: JSON.stringify({ score, comments, evaluator }) }
  )
  revalidatePath('/safety/contractor')
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

// ============ Training Certificate Actions ============

export async function getTrainingCertificates(
  params: { page?: number; page_size?: number; certificate_status?: string; keyword?: string } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.certificate_status) searchParams.set('certificate_status', params.certificate_status)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  const qs = searchParams.toString()
  const endpoint = `/safety/training-certificates${qs ? `?${qs}` : ''}`
  return fetchApi<TrainingRecord[]>(endpoint)
}

export async function getExpiringCertificates() {
  return fetchApi<TrainingRecord[]>('/safety/training-certificates/expiring')
}

// ============ HazardIdentification Actions ============

export async function getHazardIdentifications(
  params: import('@/types/safety').HazardIdentificationQueryParams = {}
) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.department) searchParams.set('department', params.department)
  if (params.overall_status) searchParams.set('overall_status', params.overall_status)
  if (params.ai_node_progress) searchParams.set('ai_node_progress', params.ai_node_progress)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/hazard-identifications${queryString ? `?${queryString}` : ''}`
  return fetchApi<import('@/types/safety').HazardIdentification[]>(endpoint)
}

export async function getHazardIdentification(id: string) {
  return fetchApi<import('@/types/safety').HazardIdentification>(
    `/safety/hazard-identifications/${id}`
  )
}

export async function createHazardIdentification(
  data: import('@/types/safety').HazardIdentificationFormData
) {
  const response = await fetchApi<import('@/types/safety').HazardIdentification>(
    '/safety/hazard-identifications',
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function updateHazardIdentification(
  id: string,
  data: Partial<import('@/types/safety').HazardIdentification>
) {
  const response = await fetchApi<import('@/types/safety').HazardIdentification>(
    `/safety/hazard-identifications/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function submitHazardIdentification(id: string) {
  const response = await fetchApi<import('@/types/safety').HazardIdentification>(
    `/safety/hazard-identifications/${id}/submit`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function runHazardScript(
  id: string,
  scriptNumber: number,
  aiOutput?: Record<string, unknown>
) {
  const body: Record<string, unknown> = { script_number: scriptNumber }
  if (aiOutput) {
    body.ai_output = aiOutput
  }
  const response = await fetchApi<import('@/types/safety').HazardIdentification>(
    `/safety/hazard-identifications/${id}/run-script`,
    { method: 'POST', body: JSON.stringify(body) }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function reviewHazardScript(
  id: string,
  scriptNumber: number,
  action: 'approved' | 'rejected'
) {
  const response = await fetchApi<import('@/types/safety').HazardIdentification>(
    `/safety/hazard-identifications/${id}/review`,
    {
      method: 'POST',
      body: JSON.stringify({ script_number: scriptNumber, action }),
    }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function uploadHazardAttachment(id: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/safety/hazard-identifications/${id}/upload`,
    { method: 'POST', body: formData }
  )
  revalidatePath('/safety/hazard-identification')
  return response.json()
}

export async function deleteHazardIdentification(id: string) {
  const response = await fetchApi<null>(
    `/safety/hazard-identifications/${id}`,
    { method: 'DELETE' }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function getSafetyEnums() {
  return fetchApi<Record<string, Array<{ value: string; label: string }>>>('/safety/enums')
}

// ============ OperationRegulation Actions ============

export async function getRegulations(params: OperationRegulationQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.position) searchParams.set('position', params.position)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/regulations${queryString ? `?${queryString}` : ''}`
  return fetchApi<OperationRegulation[]>(endpoint)
}

export async function getRegulation(id: string) {
  return fetchApi<OperationRegulation>(`/safety/regulations/${id}`)
}

export async function createRegulation(data: OperationRegulationFormData) {
  const response = await fetchApi<OperationRegulation>('/safety/regulations', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/regulation')
  return response
}

export async function updateRegulation(id: string, data: Partial<OperationRegulationFormData>) {
  const response = await fetchApi<OperationRegulation>(`/safety/regulations/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/regulation')
  return response
}

export async function deleteRegulation(id: string) {
  const response = await fetchApi<null>(`/safety/regulations/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/regulation')
  return response
}

export async function uploadRegulationDocument(id: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/safety/regulations/${id}/upload`,
    { method: 'POST', body: formData }
  )
  revalidatePath('/safety/regulation')
  return response.json()
}

// ============ RegulationRevision Actions ============

export async function getRevisions(params: RegulationRevisionQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.regulation_id) searchParams.set('regulation_id', params.regulation_id)
  if (params.revision_type) searchParams.set('revision_type', params.revision_type)
  if (params.review_opinion) searchParams.set('review_opinion', params.review_opinion)
  if (params.revision_scope) searchParams.set('revision_scope', params.revision_scope)

  const queryString = searchParams.toString()
  const endpoint = `/safety/revisions${queryString ? `?${queryString}` : ''}`
  return fetchApi<RegulationRevision[]>(endpoint)
}

export async function getRevision(id: string) {
  return fetchApi<RegulationRevision>(`/safety/revisions/${id}`)
}

export async function createRevision(data: RegulationRevisionFormData) {
  const response = await fetchApi<RegulationRevision>('/safety/revisions', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/regulation-revision')
  return response
}

export async function updateRevision(id: string, data: Partial<RegulationRevision>) {
  const response = await fetchApi<RegulationRevision>(`/safety/revisions/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/regulation-revision')
  return response
}

export async function deleteRevision(id: string) {
  const response = await fetchApi<null>(`/safety/revisions/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/regulation-revision')
  return response
}

export async function manualRevisionComplete(revisionId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/safety/revisions/${revisionId}/manual-complete`,
    { method: 'POST', body: formData }
  )
  revalidatePath('/safety/regulation-revision')
  return response.json()
}

export async function aiRevisionGenerate(revisionId: string) {
  const response = await fetchApi<{ generated_content: string }>(
    `/safety/revisions/${revisionId}/ai-generate`,
    { method: 'POST' }
  )
  return response
}

export async function aiRevisionConfirm(
  revisionId: string,
  generatedContent: string,
  documentName?: string
) {
  const params = new URLSearchParams({ generated_content: generatedContent })
  if (documentName) params.set('document_name', documentName)

  const response = await fetchApi<RegulationRevision>(
    `/safety/revisions/${revisionId}/ai-confirm?${params.toString()}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/regulation-revision')
  return response
}

export async function identifyRevisionScope(revisionId: string) {
  const response = await fetchApi<RegulationRevision>(
    `/safety/revisions/${revisionId}/identify-scope`,
    { method: 'POST' }
  )
  revalidatePath('/safety/regulation-revision')
  return response
}

// ============ HazardRevisionRecord Actions ============

export async function getHazardRevisionRecords(
  params: HazardRevisionRecordQueryParams = {}
) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.regulation_revision_id) searchParams.set('regulation_revision_id', params.regulation_revision_id)
  if (params.review_opinion) searchParams.set('review_opinion', params.review_opinion)
  if (params.identification_type) searchParams.set('identification_type', params.identification_type)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/hazard-revision-records${queryString ? `?${queryString}` : ''}`
  return fetchApi<HazardRevisionRecord[]>(endpoint)
}

export async function getHazardRevisionRecord(id: string) {
  return fetchApi<HazardRevisionRecord>(`/safety/hazard-revision-records/${id}`)
}

export async function createHazardRevisionRecord(data: HazardRevisionRecordFormData) {
  const response = await fetchApi<HazardRevisionRecord>('/safety/hazard-revision-records', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function updateHazardRevisionRecord(
  id: string,
  data: Partial<HazardRevisionRecord>
) {
  const response = await fetchApi<HazardRevisionRecord>(
    `/safety/hazard-revision-records/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function approveHazardRevision(recordId: string) {
  const response = await fetchApi<HazardRevisionRecord>(
    `/safety/hazard-revision-records/${recordId}/approve`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function deleteHazardRevisionRecord(id: string) {
  const response = await fetchApi<null>(`/safety/hazard-revision-records/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function uploadHazardRevisionDocument(recordId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/safety/hazard-revision-records/${recordId}/upload`,
    { method: 'POST', body: formData }
  )
  revalidatePath('/safety/hazard-revision')
  return response.json()
}

export async function linkRevisionToArchive(recordId: string, archiveId: string) {
  const response = await fetchApi<HazardRevisionRecord>(
    `/safety/hazard-revision-records/${recordId}/link-archive/${archiveId}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard-revision')
  return response
}

// ============ HazardRevisionArchive Actions ============

export async function getHazardRevisionArchives(
  params: HazardRevisionArchiveQueryParams = {}
) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/hazard-revision-archives${queryString ? `?${queryString}` : ''}`
  return fetchApi<HazardRevisionArchive[]>(endpoint)
}

export async function getHazardRevisionArchive(id: string) {
  return fetchApi<HazardRevisionArchive>(`/safety/hazard-revision-archives/${id}`)
}

export async function createHazardRevisionArchive(data: HazardRevisionArchiveFormData) {
  const response = await fetchApi<HazardRevisionArchive>('/safety/hazard-revision-archives', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function updateHazardRevisionArchive(
  id: string,
  data: Partial<HazardRevisionArchive>
) {
  const response = await fetchApi<HazardRevisionArchive>(
    `/safety/hazard-revision-archives/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard-revision')
  return response
}

export async function deleteHazardRevisionArchive(id: string) {
  const response = await fetchApi<null>(`/safety/hazard-revision-archives/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/hazard-revision')
  return response
}

// ============ AI Workflow Config Actions ============

export async function getAIWorkflowConfigs(
  params: import('@/types/safety').AIWorkflowConfigQueryParams = {}
) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.module_code) searchParams.set('module_code', params.module_code)
  if (params.is_enabled !== undefined) searchParams.set('is_enabled', String(params.is_enabled))

  const queryString = searchParams.toString()
  const endpoint = `/safety/ai-workflow-configs${queryString ? `?${queryString}` : ''}`
  return fetchApi<import('@/types/safety').AIWorkflowConfig[]>(endpoint)
}

export async function getAIWorkflowConfig(id: string) {
  return fetchApi<import('@/types/safety').AIWorkflowConfig>(
    `/safety/ai-workflow-configs/${id}`
  )
}

export async function createAIWorkflowConfig(
  data: import('@/types/safety').AIWorkflowConfigFormData
) {
  const response = await fetchApi<import('@/types/safety').AIWorkflowConfig>(
    '/safety/ai-workflow-configs',
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/ai-workflow-config')
  return response
}

export async function updateAIWorkflowConfig(
  id: string,
  data: Partial<import('@/types/safety').AIWorkflowConfig>
) {
  const response = await fetchApi<import('@/types/safety').AIWorkflowConfig>(
    `/safety/ai-workflow-configs/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/ai-workflow-config')
  return response
}

export async function deleteAIWorkflowConfig(id: string) {
  const response = await fetchApi<null>(`/safety/ai-workflow-configs/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/ai-workflow-config')
  return response
}

// ============ API Call Config Actions ============

export async function getAPICallConfigs(isActive?: boolean) {
  const searchParams = new URLSearchParams()
  if (isActive !== undefined) searchParams.set('is_active', String(isActive))

  const queryString = searchParams.toString()
  const endpoint = `/safety/api-call-configs${queryString ? `?${queryString}` : ''}`
  return fetchApi<import('@/types/safety').APICallConfig[]>(endpoint)
}

export async function getAPICallConfig(id: string) {
  return fetchApi<import('@/types/safety').APICallConfig>(
    `/safety/api-call-configs/${id}`
  )
}

export async function createAPICallConfig(
  data: import('@/types/safety').APICallConfigFormData
) {
  const response = await fetchApi<import('@/types/safety').APICallConfig>(
    '/safety/api-call-configs',
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/ai-workflow-config')
  return response
}

export async function updateAPICallConfig(
  id: string,
  data: Partial<import('@/types/safety').APICallConfig>
) {
  const response = await fetchApi<import('@/types/safety').APICallConfig>(
    `/safety/api-call-configs/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/ai-workflow-config')
  return response
}

export async function activateAPICallConfig(id: string) {
  const response = await fetchApi<import('@/types/safety').APICallConfig>(
    `/safety/api-call-configs/${id}/activate`,
    { method: 'POST' }
  )
  revalidatePath('/safety/ai-workflow-config')
  return response
}

export async function deleteAPICallConfig(id: string) {
  const response = await fetchApi<null>(`/safety/api-call-configs/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/ai-workflow-config')
  return response
}

// ============ SpecialOperationPersonnel Actions ============

export async function getPersonnelList(params: SpecialOperationPersonnelQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.certificate_type) searchParams.set('certificate_type', params.certificate_type)
  if (params.department) searchParams.set('department', params.department)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/special-operation-personnel${queryString ? `?${queryString}` : ''}`
  return fetchApi<SpecialOperationPersonnel[]>(endpoint)
}

export async function getPersonnel(id: string) {
  return fetchApi<SpecialOperationPersonnel>(`/safety/special-operation-personnel/${id}`)
}

export async function createPersonnel(data: SpecialOperationPersonnelFormData) {
  const response = await fetchApi<SpecialOperationPersonnel>(
    '/safety/special-operation-personnel',
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/special-ops-personnel')
  return response
}

export async function updatePersonnel(id: string, data: Partial<SpecialOperationPersonnelFormData>) {
  const response = await fetchApi<SpecialOperationPersonnel>(
    `/safety/special-operation-personnel/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/special-ops-personnel')
  return response
}

export async function deletePersonnel(id: string) {
  const response = await fetchApi<null>(`/safety/special-operation-personnel/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/special-ops-personnel')
  return response
}

// ============ SpecialOperationPermit Actions ============

export async function getPermitList(params: SpecialOperationPermitQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.operation_type) searchParams.set('operation_type', params.operation_type)
  if (params.operation_level) searchParams.set('operation_level', params.operation_level)
  if (params.keyword) searchParams.set('keyword', params.keyword)

  const queryString = searchParams.toString()
  const endpoint = `/safety/special-operation-permits${queryString ? `?${queryString}` : ''}`
  return fetchApi<SpecialOperationPermit[]>(endpoint)
}

export async function getPermit(id: string) {
  return fetchApi<SpecialOperationPermit>(`/safety/special-operation-permits/${id}`)
}

export async function createPermit(data: SpecialOperationPermitFormData) {
  const response = await fetchApi<SpecialOperationPermit>(
    '/safety/special-operation-permits',
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function updatePermit(id: string, data: Partial<SpecialOperationPermitFormData>) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}`,
    { method: 'PUT', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function deletePermit(id: string) {
  const response = await fetchApi<null>(`/safety/special-operation-permits/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function submitPermit(id: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/submit`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function approvePermit(id: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/approve`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function rejectPermit(id: string, reason: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/reject?reason=${encodeURIComponent(reason)}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function startPermit(id: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/start`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function completePermit(id: string, method: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/complete?method=${encodeURIComponent(method)}`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

export async function archivePermit(id: string) {
  const response = await fetchApi<SpecialOperationPermit>(
    `/safety/special-operation-permits/${id}/archive`,
    { method: 'POST' }
  )
  revalidatePath('/safety/special-ops-permits')
  return response
}

// ============ Safety Knowledge Article Actions ============

export async function getKnowledgeArticles(params: SafetyKnowledgeArticleQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.category) searchParams.set('category', params.category)
  if (params.status) searchParams.set('status', params.status)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  const queryString = searchParams.toString()
  const endpoint = `/safety/knowledge-articles${queryString ? '?' + queryString : ''}`
  return fetchApi<SafetyKnowledgeArticle[]>(endpoint)
}

export async function getKnowledgeArticle(id: string) {
  return fetchApi<SafetyKnowledgeArticle>(`/safety/knowledge-articles/${id}`)
}

export async function createKnowledgeArticle(data: SafetyKnowledgeArticleFormData) {
  const response = await fetchApi<SafetyKnowledgeArticle>('/safety/knowledge-articles', {
    method: 'POST', body: JSON.stringify(data),
  })
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function updateKnowledgeArticle(id: string, data: Partial<SafetyKnowledgeArticleFormData>) {
  const response = await fetchApi<SafetyKnowledgeArticle>(`/safety/knowledge-articles/${id}`, {
    method: 'PUT', body: JSON.stringify(data),
  })
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function deleteKnowledgeArticle(id: string) {
  const response = await fetchApi<null>(`/safety/knowledge-articles/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function publishKnowledgeArticle(id: string) {
  const response = await fetchApi<SafetyKnowledgeArticle>(`/safety/knowledge-articles/${id}/publish`, { method: 'POST' })
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function archiveKnowledgeArticle(id: string) {
  const response = await fetchApi<SafetyKnowledgeArticle>(`/safety/knowledge-articles/${id}/archive`, { method: 'POST' })
  revalidatePath('/safety/knowledge-base')
  return response
}

// ==================== 八大特殊作业报备 Actions ====================

export async function getSpecialOperationReports(params?: SpecialOperationReportQueryParams) {
  const query = new URLSearchParams()
  if (params) {
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    if (params.status) query.set('status', params.status)
    if (params.operation_type) query.set('operation_type', params.operation_type)
    if (params.department) query.set('department', params.department)
    if (params.keyword) query.set('keyword', params.keyword)
  }
  const qs = query.toString()
  const response = await fetchApi<SpecialOperationReport[]>(`/safety/special-operation-reports${qs ? `?${qs}` : ''}`)
  return response
}

export async function getSpecialOperationReport(id: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}`)
  return response
}

export async function createSpecialOperationReport(data: SpecialOperationReportFormData) {
  const response = await fetchApi<SpecialOperationReport>('/safety/special-operation-reports', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function updateSpecialOperationReport(id: string, data: Partial<SpecialOperationReportFormData>) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function deleteSpecialOperationReport(id: string) {
  const response = await fetchApi<void>(`/safety/special-operation-reports/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function submitSpecialOperationReport(id: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/submit`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function approveSpecialOperationReport(id: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/approve`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function rejectSpecialOperationReport(id: string, reason: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}

// ==================== 每日风险作业报备 Actions ====================

export async function getDailyRiskReports(params?: DailyRiskReportQueryParams) {
  const query = new URLSearchParams()
  if (params) {
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    if (params.status) query.set('status', params.status)
    if (params.department) query.set('department', params.department)
    if (params.report_date) query.set('report_date', params.report_date)
    if (params.keyword) query.set('keyword', params.keyword)
  }
  const qs = query.toString()
  const response = await fetchApi<DailyRiskReport[]>(`/safety/daily-risk-reports${qs ? `?${qs}` : ''}`)
  return response
}

export async function getDailyRiskReport(id: string) {
  const response = await fetchApi<DailyRiskReport>(`/safety/daily-risk-reports/${id}`)
  return response
}

export async function createDailyRiskReport(data: DailyRiskReportFormData) {
  const response = await fetchApi<DailyRiskReport>('/safety/daily-risk-reports', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function updateDailyRiskReport(id: string, data: Partial<DailyRiskReportFormData>) {
  const response = await fetchApi<DailyRiskReport>(`/safety/daily-risk-reports/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function deleteDailyRiskReport(id: string) {
  const response = await fetchApi<void>(`/safety/daily-risk-reports/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function submitDailyRiskReport(id: string) {
  const response = await fetchApi<DailyRiskReport>(`/safety/daily-risk-reports/${id}/submit`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function approveDailyRiskReport(id: string) {
  const response = await fetchApi<DailyRiskReport>(`/safety/daily-risk-reports/${id}/approve`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}

export async function rejectDailyRiskReport(id: string, reason: string) {
  const response = await fetchApi<DailyRiskReport>(`/safety/daily-risk-reports/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  return response
}


// ============ EHS变更管理 (MOC) ============

import type {
  EhsChange,
  EhsChangeFormData,
  EhsChangeQueryParams,
  OhHazardMonitor,
  OhHazardMonitorFormData,
  OhHazardMonitorQueryParams,
  OhHealthExam,
  OhHealthExamFormData,
  OhHealthExamQueryParams,
} from '@/types/safety'

// CRUD
export async function getEhsChanges(params: EhsChangeQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.change_type) searchParams.set('change_type', params.change_type)
  if (params.change_grade) searchParams.set('change_grade', params.change_grade)
  if (params.change_duration) searchParams.set('change_duration', params.change_duration)
  if (params.department) searchParams.set('department', params.department)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  const qs = searchParams.toString()
  return fetchApi<EhsChange[]>(`/safety/ehs-changes${qs ? `?${qs}` : ''}`)
}

export async function getEhsChange(id: string) {
  return fetchApi<EhsChange>(`/safety/ehs-changes/${id}`)
}

export async function createEhsChange(data: EhsChangeFormData) {
  const response = await fetchApi<EhsChange>('/safety/ehs-changes', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function updateEhsChange(id: string, data: Partial<EhsChangeFormData>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function deleteEhsChange(id: string) {
  const response = await fetchApi<void>(`/safety/ehs-changes/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/ehs-change')
  return response
}

// Workflow
export async function submitEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/submit`, { method: 'POST' })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function approveEhsChange(id: string, decision: string, comments?: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision, comments }),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function rejectEhsChange(id: string, comments?: string) {
  const params = comments ? `?comments=${encodeURIComponent(comments)}` : ''
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/reject${params}`, { method: 'POST' })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function startImplementationEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/start-implementation`, { method: 'POST' })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function commissionEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/commission`, { method: 'POST' })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function closeEhsChange(id: string, closedBy?: string, tempExpiryDate?: string, restoredDate?: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/close`, {
    method: 'POST',
    body: JSON.stringify({ closed_by: closedBy, temp_expiry_date: tempExpiryDate, restored_date: restoredDate }),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function cancelEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/cancel`, { method: 'POST' })
  revalidatePath('/safety/ehs-change')
  return response
}

// JSON sub-record operations
export async function addRiskAssessment(id: string, data: Record<string, unknown>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/risk-assessments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function updateActionItem(id: string, index: number, status: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/action-items/${index}?status=${encodeURIComponent(status)}`, { method: 'PUT' })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function updatePSSRChecklist(id: string, data: Record<string, unknown>[] | object[]) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/pssr-checklist`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change')
  return response
}

export async function submitVerification(id: string, data: Record<string, unknown>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/verification`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change')
  return response
}


// ==================== 职业危害因素监测 Actions ====================


export async function getOhHazardMonitors(params: OhHazardMonitorQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.detection_type) searchParams.set('detection_type', params.detection_type)
  if (params.workplace) searchParams.set('workplace', params.workplace)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  const qs = searchParams.toString()
  const endpoint = `/safety/oh-hazard-monitors${qs ? '?' + qs : ''}`
  return fetchApi<OhHazardMonitor[]>(endpoint)
}

export async function getOhHazardMonitor(id: string) {
  return fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}`)
}

export async function createOhHazardMonitor(data: OhHazardMonitorFormData) {
  const res = await fetchApi<OhHazardMonitor>('/safety/oh-hazard-monitors', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateOhHazardMonitor(id: string, data: Partial<OhHazardMonitorFormData>) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function deleteOhHazardMonitor(id: string) {
  const res = await fetchApi<void>(`/safety/oh-hazard-monitors/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/occupational-health')
  return res
}

// Monitor Workflow
export async function startMonitor(id: string) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/start`, { method: 'POST' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function completeMonitor(id: string) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/complete`, { method: 'POST' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function verifyMonitor(id: string, data: { verified_by?: string; comments?: string }) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/verify`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

// Monitor Sub-records
export async function addDetectionResult(id: string, data: Record<string, unknown>) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/detection-results`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateDetectionResult(id: string, index: number, data: Record<string, unknown>) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/detection-results/${index}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function deleteDetectionResult(id: string, index: number) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/detection-results/${index}`, { method: 'DELETE' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function addMonitorAbnormality(id: string, data: Record<string, unknown>) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/abnormality-records`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateMonitorAbnormalityStatus(id: string, index: number, status: string) {
  const res = await fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}/abnormality-records/${index}?status=${encodeURIComponent(status)}`, { method: 'PUT' })
  revalidatePath('/safety/occupational-health')
  return res
}


// ==================== 职业健康体检 Actions ====================


export async function getOhHealthExams(params: OhHealthExamQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.status) searchParams.set('status', params.status)
  if (params.exam_type) searchParams.set('exam_type', params.exam_type)
  if (params.department) searchParams.set('department', params.department)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  const qs = searchParams.toString()
  const endpoint = `/safety/oh-health-exams${qs ? '?' + qs : ''}`
  return fetchApi<OhHealthExam[]>(endpoint)
}

export async function getOhHealthExam(id: string) {
  return fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}`)
}

export async function createOhHealthExam(data: OhHealthExamFormData) {
  const res = await fetchApi<OhHealthExam>('/safety/oh-health-exams', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateOhHealthExam(id: string, data: Partial<OhHealthExamFormData>) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function deleteOhHealthExam(id: string) {
  const res = await fetchApi<void>(`/safety/oh-health-exams/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/occupational-health')
  return res
}

// Exam Workflow
export async function startExam(id: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/start`, { method: 'POST' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function completeExam(id: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/complete`, { method: 'POST' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function archiveExam(id: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/archive`, { method: 'POST' })
  revalidatePath('/safety/occupational-health')
  return res
}

// Exam Sub-records
export async function addExamItem(id: string, data: Record<string, unknown>) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/exam-items`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateExamItem(id: string, index: number, data: Record<string, unknown>) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/exam-items/${index}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function deleteExamItem(id: string, index: number) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/exam-items/${index}`, { method: 'DELETE' })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function setExamConclusion(id: string, conclusion: string, remarks?: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/conclusion`, {
    method: 'PUT',
    body: JSON.stringify({ conclusion, remarks }),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function addExamAbnormality(id: string, data: Record<string, unknown>) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/abnormality-records`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateExamAbnormalityStatus(id: string, index: number, status: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/abnormality-records/${index}?status=${encodeURIComponent(status)}`, { method: 'PUT' })
  revalidatePath('/safety/occupational-health')
  return res
}
