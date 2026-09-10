'use server'

import { revalidatePath } from 'next/cache'
// 注意：以下 revalidatePath 调用指向的页面路径部分仍在开发中，待对应页面创建后将自动生效
import { getAuthHeaders } from '@/lib/auth'
import { fetchApi, uploadPhoto } from './_helpers'
import { API_BASE, buildQueryString, SAFETY_BITABLE_CONFIG, SAFETY_SCHEDULER_CONFIG } from './_utils'
import type {
  AiAuditQueryParams,
  AiAuditStats,
  AiCallAuditDetail,
  AiCallAuditListItem,
  Contractor,
  ContractorFormData,
  ContractorQueryParams,
  ContractorWorkRecord,
  ContractorWorkRecordFormData,
  HazardReport,
  HazardReportFormData,
  HazardReportQueryParams,
  HazardStats,
  OperationRegulation,
  OperationRegulationFormData,
  OperationRegulationQueryParams,
  RegulationRevision,
  RegulationRevisionFormData,
  RegulationRevisionQueryParams,
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleFormData,
  SafetyKnowledgeArticleQueryParams,
  KnowledgeCategoryCounts,
  ParseDocumentResponse,
  ParseUrsDocumentResponse,
  DuplicateCheckRequest,
  DuplicateCheckResponse,
  NewVersionResponse,
  VersionChainItem,
  SemanticSearchResult,
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
  SpecialOperationReportV35Fields,
  SpecialOperationLedgerQueryParams,
  SpecialOperationLedgerStats,
  KeyRiskOperationReport,
  KeyRiskOperationQueryParams,
  KeyRiskOperationLedgerStats,
  DailyReportRecord,
  DailyReportGenerateRequest,
  DailyReportResponse,
  DailyReportStats,
  RectificationReplyRequest,
  VerifyLevelRequest,
  TrainingRecord,
  TrainingRecordFormData,
  ApiResponse,
  EhsChange,
  EhsChangeFormData,
  EhsChangeQueryParams,
  EhsChangeStats,
  // contractor admission（相关方准入）
  ContractorAdmission,
  ContractorAdmissionListItem,
  ContractorAdmissionQueryParams,
  ContractorAdmissionStats,
  // fire alarm（消防报警分析）
  FireAlarmDailyReportRequest,
  FireAlarmQueryParams,
  FireAlarmRecord,
  FireAlarmReportResponse,
  FireAlarmStats,
  FireAlarmSyncResult,
  FireAlarmWeeklyReportRequest,
  // central alarm（中控报警分析）
  CentralAlarmDailyReportRequest,
  CentralAlarmQueryParams,
  CentralAlarmRecord,
  CentralAlarmReportResponse,
  CentralAlarmStats,
  CentralAlarmSyncResult,
  // occupational health（design §八：新 OH 函数统一 code===200，写操作后 revalidatePath）
  OhAiConclusion,
  OhPerson,
  OhPersonQueryParams,
  OhPersonStats,
  OhHealthExam,
  OhHealthExamQueryParams,
  OhHealthExamFormData,
  OhExamStats,
  OhPosition,
  OhPositionQueryParams,
  OhHazardFactor,
  OhHazardFactorQueryParams,
  OhExamApplication,
  OhExamApplicationQueryParams,
  OhApplicationStats,
  OhFollowup,
  OhFollowupQueryParams,
  OhFollowupFormData,
  OhOverrideConclusionRequest,
  // knowledge
  GenerateCardResponse,
  AgentUsageStats,
  BatchGenerateCardsResponse,
  GeneratePptRequest,
  GeneratePptResponse,
  GenerateSummaryResponse,
  PptHistoryResponse,
  SyncKnowledgeResponse,
  // emergency drill
  DrillRecord,
  DrillRecordQueryParams,
  DrillDocument,
  DrillStats,
  CollectionRecord,
  CollectionStats,
  // cert warning
  CertWarningDetail,
  CertWarningSummary,
  CertWarningQueryParams,
  RenewRequest,
  // chemical inventory（危化品库存）
  ChemicalInventoryRecord,
  ChemicalInventoryQueryParams,
  ChemicalInventoryStats,
  ChemicalInventoryScanResult,
  // scheduler-config（AI 配置 + 定时任务）
  AiConfigAuditItem,
  AiConfigData,
  AiModelConfig,
  AiModelProfile,
  AiModelTestResult,
  AiScenarioAuditItem,
  AiScenarioConfig,
  FeishuGroupsData,
  FeishuPerson,
  SchedulerPreviewData,
  SchedulerRunResult,
  ScheduledTask,
  UpdateAiConfigInput,
  UpdateAiScenarioInput,
  UpdateScheduledTaskInput,
  // bitable-config（多维表格配置中心）
  BitableAuditItem,
  BitableConnection,
  BitableDomainOverview,
  BitableFieldMapping,
  BitableMappingsView,
  BitableResubscribeResult,
  BitableTestResult,
  UpdateBitableConnectionInput,
} from '@/types/safety'

// ============ HazardReport Actions ============

export async function fetchHazardStats() {
  return fetchApi<HazardStats>('/safety/hazards/stats')
}

export async function getHazards(params: HazardReportQueryParams = {}) {
  return fetchApi<HazardReport[]>(`/safety/hazards${buildQueryString(params)}`)
}

export async function getHazard(id: string) {
  return fetchApi<HazardReport>(`/safety/hazards/${id}`)
}

/** 根据部门名称查询部门负责人 */
export async function getDepartmentLeader(departmentName: string) {
  return fetchApi<{ department: string; leader_name: string | null; leader_id: string | null }>(
    `/safety/hazards/department-leader?department_name=${encodeURIComponent(departmentName)}`
  )
}

/** 根据部门名称查询分管安全员 */
export async function getDepartmentSafetyOfficer(departmentName: string) {
  return fetchApi<{ department: string; safety_officer_name: string | null; safety_officer_id: string | null }>(
    `/safety/hazards/department-safety-officer?department_name=${encodeURIComponent(departmentName)}`
  )
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


export async function replyRectification(id: string, data: RectificationReplyRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/reply`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function verifyLevel(id: string, data: VerifyLevelRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/verify-level`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/hazard')
  return response
}

export async function notifyReviewer(id: string) {
  const response = await fetchApi<{ level: number; level_label: string }>(
    `/safety/hazards/${id}/rectification/notify-reviewer`,
    { method: 'POST' }
  )
  return response
}

export async function notifyRectification(id: string) {
  const response = await fetchApi<{ target: string }>(
    `/safety/hazards/${id}/rectification/notify-rectification`,
    { method: 'POST' }
  )
  return response
}

export async function triggerRectificationReview(id: string) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/review`,
    { method: 'POST' }
  )
  return response
}

export async function reworkRectification(id: string, data: RectificationReplyRequest) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${id}/rectification/rework`,
    { method: 'POST', body: JSON.stringify(data) }
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

export async function deleteHazards(ids: string[]) {
  const results = await Promise.allSettled(
    ids.map((id) =>
      fetchApi<null>(`/safety/hazards/${id}`, { method: 'DELETE' })
    )
  )
  revalidatePath('/safety/hazard')
  const succeeded = results.filter((r) => r.status === 'fulfilled').length
  const failed = results.filter((r) => r.status === 'rejected').length
  return { succeeded, failed, total: ids.length }
}

export async function uploadHazardPhoto(id: string, file: File) {
  return uploadPhoto(`/safety/hazards/${id}/upload-photo`, file)
}

export async function uploadRectificationPhoto(id: string, file: File) {
  return uploadPhoto(`/safety/hazards/${id}/upload-rectification-photo`, file)
}

export async function runHazardAI(hazardId: string, scriptNumber: number) {
  const response = await fetchApi<HazardReport>(
    `/safety/hazards/${hazardId}/ai/run/${scriptNumber}`,
    { method: 'POST', body: '{}' }
  )
  revalidatePath('/safety/hazard')
  return response
}

// ============ Contractor Actions ============

export async function getContractors(params: ContractorQueryParams = {}) {
  return fetchApi<Contractor[]>(`/safety/contractors${buildQueryString(params)}`)
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
  if (params.position) searchParams.set('position', params.position)
  if (params.risk_level) searchParams.set('risk_level', params.risk_level)
  if (params.date_from) searchParams.set('date_from', params.date_from)
  if (params.date_to) searchParams.set('date_to', params.date_to)
  if (params.batch_id) searchParams.set('batch_id', params.batch_id)
  if (params.review_status) searchParams.set('review_status', params.review_status)

  const queryString = searchParams.toString()
  const endpoint = `/safety/hazard-identifications${queryString ? `?${queryString}` : ''}`
  return fetchApi<import('@/types/safety').HazardIdentification[]>(endpoint)
}

export async function getHIStats() {
  return fetchApi<import('@/types/safety').HazardIdentificationStats>(
    '/safety/hazard-identifications/stats'
  )
}

export async function getHILedgerStats(
  params: {
    department?: string
    position?: string
    risk_level?: string
    date_from?: string
    date_to?: string
  } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.department) searchParams.set('department', params.department)
  if (params.position) searchParams.set('position', params.position)
  if (params.risk_level) searchParams.set('risk_level', params.risk_level)
  if (params.date_from) searchParams.set('date_from', params.date_from)
  if (params.date_to) searchParams.set('date_to', params.date_to)
  const qs = searchParams.toString()
  return fetchApi<import('@/types/safety').HazardLedgerStats>(
    `/safety/hazard-identifications/ledger-stats${qs ? `?${qs}` : ''}`
  )
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

// ── 批量辨识 ──

export async function getRegulationStages(regulationId: string) {
  return fetchApi<import('@/types/safety').RegulationStagesResponse>(
    `/safety/regulations/${regulationId}/stages`
  )
}

export async function createHazardIdentificationBatch(
  data: import('@/types/safety').HazardIdentificationBatchCreateInput
) {
  const response = await fetchApi<import('@/types/safety').HazardIdentificationBatchResponse>(
    '/safety/hazard-identifications/batch',
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

// ── 手动触发（事件丢失兜底）──

export interface ManualTriggerResult {
  status: 'advanced' | 'noop'
  reason?: 'completed' | 'precondition' | 'empty_record' | 'dedup' | 'busy'
  message?: string
  next_node?: string
  script?: number | null
}

export interface ManualTriggerResponse {
  result: ManualTriggerResult
  record?: import('@/types/safety').HazardIdentification
}

export async function manualTriggerHazardIdentification(id: string) {
  const response = await fetchApi<ManualTriggerResponse>(
    `/safety/hazard-identifications/${id}/manual-trigger`,
    { method: 'POST' }
  )
  revalidatePath('/safety/hazard-identification')
  return response
}

export async function uploadHazardAttachment(id: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const authHeaders = await getAuthHeaders()
  const { 'Content-Type': _, ...uploadHeaders } = authHeaders
  const response = await fetch(
    `${API_BASE}/safety/hazard-identifications/${id}/upload`,
    { method: 'POST', headers: uploadHeaders, body: formData }
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

// ============ Hazard Identification AI Export ============

export async function parseHazardExportQuery(naturalQuery: string) {
  return fetchApi<import('@/types/safety').HazardLedgerExportParsedFilters>(
    '/safety/hazard-identifications/parse-query',
    {
      method: 'POST',
      body: JSON.stringify({ natural_query: naturalQuery }),
    }
  )
}

export async function exportHazardLedgerPdf(
  params: import('@/types/safety').HazardLedgerExportRequest
): Promise<ApiResponse<string>> {
  const authHeaders = await getAuthHeaders()
  const response = await fetch(`${API_BASE}/safety/hazard-identifications/export-pdf`, {
    method: 'POST',
    headers: { ...authHeaders },
    body: JSON.stringify(params),
  })

  if (!response.ok) {
    const errorText = await response.text()
    return { code: response.status, message: `导出失败: ${errorText}`, data: '' } as ApiResponse<string>
  }

  // 在 Server Action 中不能使用 browser API，返回 base64 给客户端处理下载
  const arrayBuffer = await response.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { code: 0, message: 'ok', data: base64 }
}

export async function exportHazardLedgerExcel(
  params: import('@/types/safety').HazardLedgerExportRequest
): Promise<ApiResponse<string>> {
  const authHeaders = await getAuthHeaders()
  const response = await fetch(`${API_BASE}/safety/hazard-identifications/export-excel`, {
    method: 'POST',
    headers: { ...authHeaders },
    body: JSON.stringify(params),
  })

  if (!response.ok) {
    const errorText = await response.text()
    return { code: response.status, message: `导出失败: ${errorText}`, data: '' } as ApiResponse<string>
  }

  // 在 Server Action 中不能使用 browser API，返回 base64 给客户端处理下载
  const arrayBuffer = await response.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { code: 0, message: 'ok', data: base64 }
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
  if (params.status) searchParams.set('status', params.status)

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
  const authHeaders = await getAuthHeaders()
  const { 'Content-Type': _, ...uploadHeaders } = authHeaders
  const response = await fetch(
    `${API_BASE}/safety/regulations/${id}/upload`,
    { method: 'POST', headers: uploadHeaders, body: formData }
  )
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`上传失败: ${response.status} ${text}`)
  }
  revalidatePath('/safety/regulation')
  return response.json()
}

// ============ SOP Generator Actions ============

export async function generateSop(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const authHeaders = await getAuthHeaders()
  const { 'Content-Type': _, ...uploadHeaders } = authHeaders
  const response = await fetch(
    `${API_BASE}/safety/regulations/generate`,
    { method: 'POST', headers: uploadHeaders, body: formData }
  )
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`生成失败 (${response.status}): ${text}`)
  }
  revalidatePath('/safety/regulation')
  return response.json()
}

export async function updateSopContent(regulationId: string, content: string, status?: string) {
  const response = await fetchApi<OperationRegulation>(
    `/safety/regulations/${regulationId}/content`,
    { method: 'PUT', body: JSON.stringify({ content, status }) }
  )
  revalidatePath('/safety/regulation')
  return response
}

export async function exportSopPdf(
  regulationId: string,
  format: 'pdf' | 'docx' = 'pdf',
): Promise<ApiResponse<Blob>> {
  const authHeaders = await getAuthHeaders()
  const { 'Content-Type': _, ...headers } = authHeaders
  const response = await fetch(
    `${API_BASE}/safety/regulations/${regulationId}/export?format=${format}`,
    { method: 'POST', headers }
  )
  if (!response.ok) {
    const text = await response.text()
    return { code: response.status, message: `导出 ${format === 'docx' ? 'WORD' : 'PDF'} 失败: ${text}` } as ApiResponse<Blob>
  }
  const blob = await response.blob()
  return { code: 0, message: 'ok', data: blob }
}

export async function retryAiReview(regulationId: string) {
  const response = await fetchApi<{ regulation_id: string; ai_review_status: string }>(
    `/safety/regulations/${regulationId}/ai-review`,
    { method: 'POST' }
  )
  revalidatePath('/safety/regulation')
  return response
}

export async function reviseRegulation(
  regulationId: string,
  content: string,
  revisionOpinion?: string,
  reviserName?: string,
) {
  const response = await fetchApi<{
    regulation_id: string
    revision_id: string
    revision_no: string
    regulation_name: string
    status: string
  }>(`/safety/regulations/${regulationId}/revise`, {
    method: 'POST',
    body: JSON.stringify({
      content,
      revision_opinion: revisionOpinion || null,
      reviser_name: reviserName || null,
    }),
  })
  revalidatePath('/safety/regulation')
  return response
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
  const authHeaders = await getAuthHeaders()
  const { 'Content-Type': _, ...uploadHeaders } = authHeaders
  const response = await fetch(
    `${API_BASE}/safety/revisions/${revisionId}/manual-complete`,
    { method: 'POST', headers: uploadHeaders, body: formData }
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

// ── AI 智能解析 ──

export async function parseKnowledgeDocument(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const headers = await getAuthHeaders()
  // Remove Content-Type so browser sets multipart boundary
  delete (headers as Record<string, string>)['Content-Type']
  const res = await fetch(`${API_BASE}/safety/knowledge-articles/parse`, {
    method: 'POST',
    headers,
    body: formData,
  })
  return res.json() as Promise<ApiResponse<ParseDocumentResponse>>
}

export async function batchParseKnowledgeDocuments(files: File[]) {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  const headers = await getAuthHeaders()
  delete (headers as Record<string, string>)['Content-Type']
  const res = await fetch(`${API_BASE}/safety/knowledge-articles/batch-parse`, {
    method: 'POST',
    headers,
    body: formData,
  })
  return res.json() as Promise<ApiResponse<ParseDocumentResponse[]>>
}

// ── 附件上传 ──

export async function uploadKnowledgeAttachment(articleId: string, file: File) {
  return uploadPhoto(`/safety/knowledge-articles/${articleId}/upload`, file)
}

// ── 重复检测 ──

export async function checkDuplicateArticle(data: DuplicateCheckRequest) {
  return fetchApi<DuplicateCheckResponse>('/safety/knowledge-articles/check-duplicate', {
    method: 'POST', body: JSON.stringify(data),
  })
}

// ── 版本管理 ──

export async function getArticleVersions(id: string) {
  return fetchApi<VersionChainItem[]>(`/safety/knowledge-articles/${id}/versions`)
}

export async function createNewArticleVersion(id: string) {
  const response = await fetchApi<NewVersionResponse>(`/safety/knowledge-articles/${id}/new-version`, { method: 'POST' })
  revalidatePath('/safety/knowledge-base')
  return response
}

// ── 语义搜索 ──

export async function semanticSearchArticles(q: string, page = 1, page_size = 20) {
  const params = new URLSearchParams({ q, page: String(page), page_size: String(page_size) })
  return fetchApi<SemanticSearchResult[]>(`/safety/knowledge-articles/semantic-search?${params.toString()}`)
}

// ── 分类计数（全库） ──

export async function getKnowledgeCategoryCounts() {
  return fetchApi<KnowledgeCategoryCounts>('/safety/knowledge-articles/category-counts')
}

// ── 知识卡片管理 ──

export async function generateKnowledgeCard(articleId: string) {
  const response = await fetchApi<GenerateCardResponse>(
    `/safety/knowledge-articles/${articleId}/generate-card`,
    { method: 'POST' }
  )
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function getAgentUsageStats(articleId: string) {
  return fetchApi<AgentUsageStats>(`/safety/knowledge-articles/${articleId}/agent-stats`)
}

export async function batchGenerateKnowledgeCards(articleIds: string[]) {
  const response = await fetchApi<BatchGenerateCardsResponse>(
    '/safety/knowledge-articles/batch/generate-cards',
    { method: 'POST', body: JSON.stringify({ article_ids: articleIds }) }
  )
  revalidatePath('/safety/knowledge-base')
  return response
}

// ── AI PPT 生成 ──

export async function generatePpt(articleId: string, data: GeneratePptRequest) {
  const response = await fetchApi<GeneratePptResponse>(
    `/safety/knowledge-articles/${articleId}/generate-ppt`,
    { method: 'POST', body: JSON.stringify(data) }
  )
  revalidatePath('/safety/knowledge-base')
  return response
}

export async function getPptHistory(articleId: string) {
  return fetchApi<PptHistoryResponse>(`/safety/knowledge-articles/${articleId}/ppt-history`)
}

// ── AI 摘要生成 ──

export async function generateSummary(articleId: string) {
  const response = await fetchApi<GenerateSummaryResponse>(
    `/safety/knowledge-articles/${articleId}/generate-summary`,
    { method: 'POST' }
  )
  revalidatePath('/safety/knowledge-base')
  return response
}

// ── Bitable 同步 ──

export async function syncKnowledgeArticles() {
  const response = await fetchApi<SyncKnowledgeResponse>(
    '/safety/knowledge-articles/sync',
    { method: 'POST' }
  )
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
    if (params.operation_level) query.set('operation_level', params.operation_level)
    if (params.risk_level) query.set('risk_level', params.risk_level)
    if (params.department) query.set('department', params.department)
    if (params.date_from) query.set('date_from', params.date_from)
    if (params.date_to) query.set('date_to', params.date_to)
    if (params.keyword) query.set('keyword', params.keyword)
    if (params.is_critical !== undefined) query.set('is_critical', String(params.is_critical))
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
  revalidatePath('/safety/special-ops')

  return response
}

export async function updateSpecialOperationReport(id: string, data: Partial<SpecialOperationReportFormData>) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  revalidatePath('/safety/special-ops')

  return response
}

export async function updateSpecialOperationReportV35(
  id: string,
  data: SpecialOperationReportV35Fields,
) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/risk-reporting')
  revalidatePath('/safety/special-ops')
  return response
}

export async function deleteSpecialOperationReport(id: string) {
  const response = await fetchApi<null>(`/safety/special-operation-reports/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/risk-reporting')

  return response
}

export async function submitSpecialOperationReport(id: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/submit`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  revalidatePath('/safety/special-ops')

  return response
}

export async function approveSpecialOperationReport(id: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/approve`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  revalidatePath('/safety/special-ops')

  return response
}

export async function rejectSpecialOperationReport(id: string, reason: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' })
  revalidatePath('/safety/risk-reporting')
  revalidatePath('/safety/special-ops')

  return response
}

export async function setSpecialOperationReportCritical(id: string, is_critical: boolean, reason?: string) {
  const response = await fetchApi<SpecialOperationReport>(`/safety/special-operation-reports/${id}/critical`, {
    method: 'PUT',
    body: JSON.stringify({ is_critical, reason }),
  })
  revalidatePath('/safety/special-ops')

  return response
}

// ==================== 特殊作业台账 Actions ====================

export async function getSpecialOperationLedger(params?: SpecialOperationLedgerQueryParams) {
  const query = new URLSearchParams()
  if (params) {
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    if (params.operation_type) query.set('operation_type', params.operation_type)
    if (params.operation_level) query.set('operation_level', params.operation_level)
    if (params.risk_level) query.set('risk_level', params.risk_level)
    if (params.department) query.set('department', params.department)
    if (params.date_from) query.set('date_from', params.date_from)
    if (params.date_to) query.set('date_to', params.date_to)
    if (params.keyword) query.set('keyword', params.keyword)
    if (params.is_critical !== undefined) query.set('is_critical', String(params.is_critical))
  }
  const qs = query.toString()
  const response = await fetchApi<SpecialOperationReport[]>(`/safety/special-operation-ledger${qs ? `?${qs}` : ''}`)
  return response
}

export async function getSpecialOperationLedgerStats() {
  const response = await fetchApi<SpecialOperationLedgerStats[]>('/safety/special-operation-ledger/stats')
  return response
}

// ==================== 关键风险作业报备 Actions（Bitable 只读） ====================

export async function getKeyRiskOperationReports(params?: KeyRiskOperationQueryParams) {
  const query = new URLSearchParams()
  if (params) {
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    if (params.department) query.set('department', params.department)
    if (params.area) query.set('area', params.area)
    if (params.operation_content) query.set('operation_content', params.operation_content)
    if (params.apply_status) query.set('apply_status', params.apply_status)
    if (params.date_from) query.set('date_from', params.date_from)
    if (params.date_to) query.set('date_to', params.date_to)
    if (params.keyword) query.set('keyword', params.keyword)
  }
  const qs = query.toString()
  return fetchApi<KeyRiskOperationReport[]>(`/safety/key-risk-operation-reports${qs ? `?${qs}` : ''}`)
}

export async function getKeyRiskOperationReport(id: string) {
  return fetchApi<KeyRiskOperationReport>(`/safety/key-risk-operation-reports/${id}`)
}

export async function getKeyRiskOperationStats() {
  return fetchApi<KeyRiskOperationLedgerStats>('/safety/key-risk-operation-reports/stats')
}

export async function syncKeyRiskOperations() {
  return fetchApi<{ created: number; updated: number; deleted: number; skipped_deleted: number }>(
    '/safety/key-risk-operation-reports/sync',
    { method: 'POST' },
  )
}

// ============ SpecialOperationDailyReport Actions ============

export async function getDailyRecords(params?: {
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}) {
  const queryParts: string[] = []
  if (params?.date_from) queryParts.push(`date_from=${params.date_from}`)
  if (params?.date_to) queryParts.push(`date_to=${params.date_to}`)
  if (params?.page) queryParts.push(`page=${params.page}`)
  if (params?.page_size) queryParts.push(`page_size=${params.page_size}`)
  const qs = queryParts.length > 0 ? `?${queryParts.join('&')}` : ''
  return fetchApi<DailyReportRecord[]>(`/safety/special-operation-daily-report/records${qs}`)
}

export async function generateDailyReport(data: DailyReportGenerateRequest) {
  return fetchApi<DailyReportResponse>('/safety/special-operation-daily-report/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function syncDailyReportData() {
  return fetchApi<{ synced_count: number }>('/safety/special-operation-daily-report/sync', {
    method: 'POST',
  })
}

export async function getDailyReportStats(target_date?: string) {
  const qs = target_date ? `?target_date=${target_date}` : ''
  return fetchApi<DailyReportStats>(`/safety/special-operation-daily-report/stats${qs}`)
}


// ============ FireAlarm Actions（消防报警分析） ============

export async function getFireAlarmRecords(params: FireAlarmQueryParams = {}) {
  return fetchApi<FireAlarmRecord[]>(`/safety/fire-alarms/records${buildQueryString(params)}`)
}

export async function getFireAlarmStats() {
  return fetchApi<FireAlarmStats>('/safety/fire-alarms/stats')
}

/** 手动触发 Bitable 全量同步（upsert + 软删除），成功后刷新页面 SSR 预取 */
export async function syncFireAlarmData() {
  const response = await fetchApi<FireAlarmSyncResult>('/safety/fire-alarms/sync', {
    method: 'POST',
  })
  revalidatePath('/safety/fire-alarms')
  return response
}

/** 生成日报：AI 逐条分析并回写记录 + 汇总 Markdown + 推送；成功后 AI 字段变化需刷新页面 */
export async function generateFireAlarmDailyReport(data: FireAlarmDailyReportRequest = {}) {
  const response = await fetchApi<FireAlarmReportResponse>('/safety/fire-alarms/daily-report/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/fire-alarms')
  return response
}

/** 生成周报：周级聚合 + 重复/集中问题识别 + 推送；成功后同样刷新页面 */
export async function generateFireAlarmWeeklyReport(data: FireAlarmWeeklyReportRequest = {}) {
  const response = await fetchApi<FireAlarmReportResponse>('/safety/fire-alarms/weekly-report/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/fire-alarms')
  return response
}


// ============ CentralAlarm Actions（中控报警分析） ============

export async function getCentralAlarmRecords(params: CentralAlarmQueryParams = {}) {
  return fetchApi<CentralAlarmRecord[]>(`/safety/central-alarms/records${buildQueryString(params)}`)
}

export async function getCentralAlarmStats() {
  return fetchApi<CentralAlarmStats>('/safety/central-alarms/stats')
}

/** 手动触发 Bitable 多表全量同步（upsert + 软删除），成功后刷新页面 */
export async function syncCentralAlarmData() {
  const response = await fetchApi<CentralAlarmSyncResult>('/safety/central-alarms/sync', {
    method: 'POST',
  })
  revalidatePath('/safety/central-alarms')
  return response
}

/** 生成日报：AI 逐条分析并回写记录 + 汇总 Markdown + 推送；成功后刷新页面 */
export async function generateCentralAlarmDailyReport(data: CentralAlarmDailyReportRequest = {}) {
  const response = await fetchApi<CentralAlarmReportResponse>('/safety/central-alarms/daily-report/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/central-alarms')
  return response
}


// ============ EHS变更管理 (MOC) ============

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
  if (params.source) searchParams.set('source', params.source)
  if (params.feishu_table_id) searchParams.set('feishu_table_id', params.feishu_table_id)
  if (params.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params.sort_order) searchParams.set('sort_order', params.sort_order)
  const qs = searchParams.toString()
  return fetchApi<EhsChange[]>(`/safety/ehs-changes${qs ? `?${qs}` : ''}`)
}

export async function getEhsChange(id: string) {
  return fetchApi<EhsChange>(`/safety/ehs-changes/${id}`)
}

export async function getEhsChangeStats(feishuTableId: string, source?: string) {
  const qs = new URLSearchParams()
  if (feishuTableId) qs.set('feishu_table_id', feishuTableId)
  if (source) qs.set('source', source)
  return fetchApi<EhsChangeStats>(`/safety/ehs-changes/stats${qs.toString() ? `?${qs.toString()}` : ''}`)
}

export async function runEhsAiReview(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/ai/audit`, {
    method: 'POST',
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function createEhsChange(data: EhsChangeFormData) {
  const response = await fetchApi<EhsChange>('/safety/ehs-changes', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function updateEhsChange(id: string, data: Partial<EhsChangeFormData>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function deleteEhsChange(id: string) {
  const response = await fetchApi<null>(`/safety/ehs-changes/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

// Workflow
export async function submitEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/submit`, { method: 'POST' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function approveEhsChange(id: string, decision: string, comments?: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision, comments }),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function rejectEhsChange(id: string, comments?: string) {
  const params = comments ? `?comments=${encodeURIComponent(comments)}` : ''
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/reject${params}`, { method: 'POST' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function startImplementationEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/start-implementation`, { method: 'POST' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function commissionEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/commission`, { method: 'POST' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function closeEhsChange(id: string, closedBy?: string, tempExpiryDate?: string, restoredDate?: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/close`, {
    method: 'POST',
    body: JSON.stringify({ closed_by: closedBy, temp_expiry_date: tempExpiryDate, restored_date: restoredDate }),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function cancelEhsChange(id: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/cancel`, { method: 'POST' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

// JSON sub-record operations
export async function addRiskAssessment(id: string, data: Record<string, unknown>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/risk-assessments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function updateActionItem(id: string, index: number, status: string) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/action-items/${index}?status=${encodeURIComponent(status)}`, { method: 'PUT' })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function updatePSSRChecklist(id: string, data: Record<string, unknown>[] | object[]) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/pssr-checklist`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}

export async function submitVerification(id: string, data: Record<string, unknown>) {
  const response = await fetchApi<EhsChange>(`/safety/ehs-changes/${id}/verification`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/apply')
  revalidatePath('/safety/ehs-change/acceptance')
  return response
}


// ==================== 职业健康管理 Actions（design §八；监测废弃已删除） ====================

// ── 人员台账 oh/persons ──

export async function getOhPersons(params: OhPersonQueryParams = {}) {
  return fetchApi<OhPerson[]>(`/safety/oh/persons${buildQueryString(params)}`)
}

export async function getOhPerson(id: string) {
  return fetchApi<OhPerson>(`/safety/oh/persons/${id}`)
}

/** 该人员的体检记录链 */
export async function getOhPersonExams(id: string) {
  return fetchApi<OhHealthExam[]>(`/safety/oh/persons/${id}/exams`)
}

export async function getOhPersonStats() {
  return fetchApi<OhPersonStats>('/safety/oh/persons/stats')
}

/** 手动触发总表回填（取最近一次体检 → last_exam_* + exam_record_ids + Bitable 回写） */
export async function syncOhPerson(id: string) {
  const res = await fetchApi<OhPerson>(`/safety/oh/persons/${id}/sync`, {
    method: 'POST',
  })
  revalidatePath('/safety/occupational-health')
  return res
}

// ── 体检记录 oh-health-exams（前缀兼容保留） ──

export async function getOhExams(params: OhHealthExamQueryParams = {}) {
  return fetchApi<OhHealthExam[]>(`/safety/oh-health-exams${buildQueryString(params)}`)
}

export async function getOhExam(id: string) {
  return fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}`)
}

export async function getOhExamEnums() {
  return fetchApi<{
    exam_type: Array<{ value: string; label: string }>
    status: Array<{ value: string; label: string }>
    ai_conclusion: Array<{ value: string; label: string }>
    ai_parse_status: Array<{ value: string; label: string }>
  }>('/safety/oh-health-exams/enums')
}

export async function createOhExam(data: OhHealthExamFormData) {
  const res = await fetchApi<OhHealthExam>('/safety/oh-health-exams', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function updateOhExam(id: string, data: Partial<OhHealthExamFormData>) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function deleteOhExam(id: string) {
  const res = await fetchApi<null>(`/safety/oh-health-exams/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/occupational-health')
  return res
}

/** 手动触发/重试 AI 解析 */
export async function parseOhExam(id: string) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/parse`, {
    method: 'POST',
  })
  revalidatePath('/safety/occupational-health')
  return res
}

/** 人工覆盖 AI 结论（后端请求体字段为 override_conclusion，前端入参按 design §八 为 conclusion） */
export async function overrideOhExamConclusion(
  id: string,
  data: { conclusion: OhAiConclusion | string; notes?: string }
) {
  const res = await fetchApi<OhHealthExam>(`/safety/oh-health-exams/${id}/override-conclusion`, {
    method: 'POST',
    body: JSON.stringify({
      override_conclusion: data.conclusion,
      notes: data.notes,
    } satisfies OhOverrideConclusionRequest),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function getOhExamStats() {
  return fetchApi<OhExamStats>('/safety/oh-health-exams/stats')
}

/** 该体检的异常随访列表 */
export async function getOhExamFollowups(id: string) {
  return fetchApi<OhFollowup[]>(`/safety/oh-health-exams/${id}/followups`)
}

// ── 岗位危害 oh/positions ──

export async function getOhPositions(params: OhPositionQueryParams = {}) {
  return fetchApi<OhPosition[]>(`/safety/oh/positions${buildQueryString(params)}`)
}

export async function getOhPosition(id: string) {
  return fetchApi<OhPosition>(`/safety/oh/positions/${id}`)
}

// ── 危害因素 PPE 字典 oh/hazard-factors ──

export async function getOhHazardFactors(params: OhHazardFactorQueryParams = {}) {
  return fetchApi<OhHazardFactor[]>(`/safety/oh/hazard-factors${buildQueryString(params)}`)
}

export async function getOhHazardFactor(id: string) {
  return fetchApi<OhHazardFactor>(`/safety/oh/hazard-factors/${id}`)
}

/** 42 项标准危害因素字典（前端 HAZARD_FACTOR_OPTIONS 兜底，运行时校验） */
export async function getOhHazardFactorEnums() {
  return fetchApi<string[]>('/safety/oh/hazard-factors/enums')
}

// ── 转岗离岗申请 oh/applications ──

export async function getOhApplications(params: OhExamApplicationQueryParams = {}) {
  return fetchApi<OhExamApplication[]>(`/safety/oh/applications${buildQueryString(params)}`)
}

export async function getOhApplication(id: string) {
  return fetchApi<OhExamApplication>(`/safety/oh/applications/${id}`)
}

/** 手动触发差异分析 */
export async function analyzeOhApplication(id: string) {
  const res = await fetchApi<OhExamApplication>(`/safety/oh/applications/${id}/analyze`, {
    method: 'POST',
  })
  revalidatePath('/safety/occupational-health')
  return res
}

export async function getOhApplicationStats() {
  return fetchApi<OhApplicationStats>('/safety/oh/applications/stats')
}

// ── 异常随访 oh/followups ──

export async function getOhFollowups(params: OhFollowupQueryParams = {}) {
  return fetchApi<OhFollowup[]>(`/safety/oh/followups${buildQueryString(params)}`)
}

/** 手动补录（exam_id 或 person_id 必填其一） */
export async function createOhFollowup(data: OhFollowupFormData) {
  const res = await fetchApi<OhFollowup>('/safety/oh/followups', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

/** 更新随访处置（action_taken → open 自动流转 followed） */
export async function updateOhFollowup(id: string, data: Partial<OhFollowupFormData>) {
  const res = await fetchApi<OhFollowup>(`/safety/oh/followups/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

/** 关闭随访闭环（followed → closed） */
export async function closeOhFollowup(id: string, actionTaken: string) {
  const res = await fetchApi<OhFollowup>(`/safety/oh/followups/${id}/close`, {
    method: 'POST',
    body: JSON.stringify({ action_taken: actionTaken }),
  })
  revalidatePath('/safety/occupational-health')
  return res
}

// ============ Business Agent (业务 Agent 对话) ============

export async function chatWithAgent(message: string, sessionId?: string) {
  const res = await fetchApi<{
    session_id: string
    answer: string
    pending_action_id: string | null
    pending_action: {
      tool_name: string
      arguments: Record<string, unknown>
      summary: string
      status: string
    } | null
    sources: {
      doc_title: string
      article_ref: string
      chunk_text: string
      doc_category: string
      feishu_url: string
    }[] | null
  }>(
    '/safety/agent/chat',
    {
      method: 'POST',
      body: JSON.stringify({ message, session_id: sessionId || null }),
    },
  )
  return res
}

export async function confirmAgentAction(actionId: string, approved: boolean) {
  const res = await fetchApi<{
    session_id: string
    answer: string
    executed: boolean
  }>(
    `/safety/agent/actions/${actionId}/confirm?approved=${approved}`,
    { method: 'POST' },
  )
  return res
}

export async function getAgentSession(sessionId: string) {
  const res = await fetchApi<{
    id: string
    channel: string
    title: string | null
    message_count: number
    role: string | null
    last_active_at: string | null
  }>(
    `/safety/agent/sessions/${sessionId}`,
    { method: 'GET' },
  )
  return res
}

// ═══════════════════════════════════════════════════════════════
// AI 调用审计
// ═══════════════════════════════════════════════════════════════

export async function listAiCallAudits(params?: AiAuditQueryParams) {
  return fetchApi<AiCallAuditListItem[]>(
    `/safety/ai-audits${buildQueryString(params ?? {})}`,
  )
}

export async function getAiCallAudit(id: string) {
  return fetchApi<AiCallAuditDetail>(`/safety/ai-audits/${id}`)
}

export async function getAiAuditStats(params?: {
  days?: number
  date_from?: string
  date_to?: string
}) {
  return fetchApi<AiAuditStats>(
    `/safety/ai-audits/stats${buildQueryString(params ?? { days: 7 })}`,
  )
}

// ═══════════════════════════════════════════════════════════════
// 应急演练管理（单表模型，三环节：计划→实施→复核）
// ═══════════════════════════════════════════════════════════════

// ── 枚举 & 统计 ──

export async function getDrillStats() {
  return fetchApi<DrillStats>('/safety/emergency-drills/stats')
}

// ── 列表 & 详情 ──

export async function getDrillRecords(params: DrillRecordQueryParams = {}) {
  return fetchApi<DrillRecord[]>(
    `/safety/emergency-drills${buildQueryString(params)}`,
  )
}

// ── AI 方案生成 ──

export async function generateDrillPlan(recordId: string) {
  const response = await fetchApi<DrillDocument>(
    `/safety/emergency-drills/${recordId}/generate-plan`,
    { method: 'POST' },
  )
  revalidatePath('/safety/emergency-drill')
  return response
}

// ── AI 评估表生成 ──

export async function generateDrillEval(recordId: string) {
  const response = await fetchApi<DrillDocument>(
    `/safety/emergency-drills/${recordId}/generate-eval`,
    { method: 'POST' },
  )
  revalidatePath('/safety/emergency-drill')
  return response
}

export async function getDrillDocuments(recordId: string) {
  return fetchApi<DrillDocument[]>(
    `/safety/emergency-drills/${recordId}/documents`,
  )
}

// ── 隐患追踪 ──

export async function createHazardsFromIssues(recordId: string) {
  const response = await fetchApi<{ hazard_id: string; description: string }[]>(
    `/safety/emergency-drills/${recordId}/create-hazards`,
    { method: 'POST' },
  )
  revalidatePath('/safety/emergency-drill')
  return response
}

// ═══════════════════════════════════════════════════════════════
// 演练计划收录
// ═══════════════════════════════════════════════════════════════

export async function getCollectionRecords(params: {
  page?: number
  page_size?: number
  parse_status?: string
} = {}) {
  return fetchApi<CollectionRecord[]>(
    `/safety/emergency-drills/collection${buildQueryString(params)}`,
  )
}

export async function getCollectionStats() {
  return fetchApi<CollectionStats>('/safety/emergency-drills/collection-stats')
}

// ==================== URS 智能审核 Actions ====================

export async function getURsReports(params: import('@/types/safety').URSQueryParams = {}) {
  return fetchApi<import('@/types/safety').URSReport[]>(
    `/safety/urs-reports${buildQueryString(params)}`,
  )
}

export async function getURsStats() {
  return fetchApi<import('@/types/safety').URSStats>('/safety/urs-reports/stats')
}

export async function createURS(data: Partial<import('@/types/safety').URSReport>) {
  const response = await fetchApi<import('@/types/safety').URSReport>('/safety/urs-reports', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function parseUrsDocument(documentText: string) {
  return fetchApi<Record<string, string>>('/safety/urs-reports/parse-document', {
    method: 'POST',
    body: JSON.stringify({ document_text: documentText }),
  })
}

export async function uploadUrsDocument(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const headers = await getAuthHeaders()
  // Remove Content-Type so browser sets multipart boundary
  delete (headers as Record<string, string>)['Content-Type']
  const res = await fetch(`${API_BASE}/safety/urs-reports/parse-upload`, {
    method: 'POST',
    headers,
    body: formData,
  })
  return res.json() as Promise<ApiResponse<ParseUrsDocumentResponse>>
}

export async function getURsReport(id: string) {
  return fetchApi<import('@/types/safety').URSReport>(`/safety/urs-reports/${id}`)
}

export async function updateURS(id: string, data: Partial<import('@/types/safety').URSReport>) {
  const response = await fetchApi<import('@/types/safety').URSReport>(`/safety/urs-reports/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function deleteURS(id: string) {
  const response = await fetchApi(`/safety/urs-reports/${id}`, { method: 'DELETE' })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function submitURS(id: string) {
  const response = await fetchApi<import('@/types/safety').URSReport>(`/safety/urs-reports/${id}/submit`, {
    method: 'POST',
  })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function confirmURsAssessment(id: string, data: { comment?: string; corrections?: Record<string, string> }) {
  const response = await fetchApi<import('@/types/safety').URSReport>(
    `/safety/urs-reports/${id}/assessment/confirm`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function runURsAdaptation(id: string) {
  const response = await fetchApi<import('@/types/safety').URSReport>(`/safety/urs-reports/${id}/adaptation/run`, {
    method: 'POST',
  })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function getURsItems(id: string) {
  return fetchApi<import('@/types/safety').URSStandardItem[]>(`/safety/urs-reports/${id}/items`)
}

export async function reviewURsItemsBatch(
  id: string,
  items: Array<{ item_id: string; verdict: string; comment?: string; rectification_required?: boolean }>,
) {
  const response = await fetchApi<import('@/types/safety').URSStandardItem[]>(
    `/safety/urs-reports/${id}/items/batch`,
    { method: 'PUT', body: JSON.stringify({ items }) },
  )
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function generateURsConclusion(id: string) {
  const response = await fetchApi<import('@/types/safety').URSReport>(
    `/safety/urs-reports/${id}/conclusion/generate`,
    { method: 'POST' },
  )
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function exportURsReviewPdf(reportId: string): Promise<ApiResponse<string>> {
  const authHeaders = await getAuthHeaders()
  const response = await fetch(`${API_BASE}/safety/urs-reports/${reportId}/export-pdf`, {
    method: 'POST',
    headers: { ...authHeaders },
  })

  // 后端业务错误以 HTTP 200 + application/json（ApiResponse 约定）返回，
  // 不能只靠 response.ok 判断失败；仅当响应体为 application/pdf 才算成功。
  const contentType = response.headers.get('content-type') ?? ''
  if (!response.ok || !contentType.includes('application/pdf')) {
    const errorText = await response.text()
    try {
      const json = JSON.parse(errorText)
      const code = typeof json.code === 'number' ? json.code : response.status
      return { code, message: json.message || `导出失败: ${errorText}`, data: '' } as ApiResponse<string>
    } catch {
      return { code: response.status, message: `导出失败: ${errorText}`, data: '' } as ApiResponse<string>
    }
  }

  // Server Action 中不能使用浏览器 API，返回 base64 给客户端触发下载
  const arrayBuffer = await response.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { code: 0, message: 'ok', data: base64 }
}

export async function submitURsAppeal(id: string, reason: string) {
  const response = await fetchApi<import('@/types/safety').URSReport>(`/safety/urs-reports/${id}/appeal`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
  revalidatePath('/safety/ehs-change/urs')
  return response
}

export async function getURsDocuments(id: string) {
  return fetchApi<Array<{ id: string; doc_type: string; title: string; content_json: unknown; version: number; created_at?: string }>>(
    `/safety/urs-reports/${id}/documents`,
  )
}

export async function getURsEnums() {
  return fetchApi<{
    equipment_categories: Array<{ value: string; label: string }>
    procurement_purposes: Array<{ value: string; label: string }>
    risk_levels: Array<{ value: string; label: string }>
    status_options: Array<{ value: string; label: string }>
    risk_dimension_keys: string[]
  }>('/safety/urs-reports/enums')
}

// ═══════════════════════════════════════════════════════════════
// MSDS 智能提取入库
// ═══════════════════════════════════════════════════════════════

type MsdsCollectionRecordT = import('@/types/safety').MsdsCollectionRecord
type MsdsDocumentT = import('@/types/safety').MsdsDocument
type MsdsStatsT = import('@/types/safety').MsdsStats

export async function getMsdsStats() {
  return fetchApi<MsdsStatsT>('/safety/msds/stats')
}

export async function getMsdsCollections(
  params: import('@/types/safety').MsdsCollectionQueryParams = {},
) {
  return fetchApi<MsdsCollectionRecordT[]>(
    `/safety/msds/collection${buildQueryString(params)}`,
  )
}

export async function getMsdsCollection(id: string) {
  return fetchApi<MsdsCollectionRecordT>(`/safety/msds/collection/${id}`)
}

export async function retryMsdsParse(collectionId: string) {
  const response = await fetchApi<MsdsCollectionRecordT>(
    `/safety/msds/collection/${collectionId}/parse`,
    { method: 'POST' },
  )
  revalidatePath('/safety/msds')
  return response
}

export async function getMsdsDocuments(
  params: import('@/types/safety').MsdsDocumentQueryParams = {},
) {
  return fetchApi<MsdsDocumentT[]>(`/safety/msds${buildQueryString(params)}`)
}

export async function getMsdsDocument(id: string) {
  return fetchApi<MsdsDocumentT>(`/safety/msds/${id}`)
}

// ============ 相关方准入条件审核 Actions（contractor-admission） ============

/** 相关方准入列表（分页 + 筛选） */
export async function getContractorAdmissions(params: ContractorAdmissionQueryParams = {}) {
  const searchParams = new URLSearchParams()
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))
  if (params.related_party_type) searchParams.set('related_party_type', params.related_party_type)
  if (params.submit_status) searchParams.set('submit_status', params.submit_status)
  if (params.ai_review_status) searchParams.set('ai_review_status', params.ai_review_status)
  if (params.ai_conclusion) searchParams.set('ai_conclusion', params.ai_conclusion)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params.sort_order) searchParams.set('sort_order', params.sort_order)
  const qs = searchParams.toString()
  return fetchApi<ContractorAdmissionListItem[]>(
    `/safety/contractor-admissions${qs ? `?${qs}` : ''}`,
  )
}

/** 相关方准入 KPI 统计 */
export async function getContractorAdmissionStats() {
  return fetchApi<ContractorAdmissionStats>('/safety/contractor-admissions/stats')
}

/** 相关方准入详情 */
export async function getContractorAdmissionDetail(id: string) {
  return fetchApi<ContractorAdmission>(`/safety/contractor-admissions/${id}`)
}

/** 手动触发单条相关方准入 AI 审核（三维度报告 + 回填 Bitable） */
export async function runAdmissionReview(id: string) {
  const response = await fetchApi<ContractorAdmission>(
    `/safety/contractor-admissions/${id}/ai/audit`,
    { method: 'POST' },
  )
  revalidatePath('/safety/contractor-admission')
  return response
}

// ============ 持证到期预警 Actions（cert-warning） ============

/** 获取持证到期预警明细（列表 + 筛选 status_level/department/cert_category/days_within + 分页） */
export async function fetchCertWarnings(params: CertWarningQueryParams = {}) {
  return fetchApi<CertWarningDetail[]>(`/safety/cert-warnings${buildQueryString(params)}`)
}

/** 获取持证到期预警汇总（6 档人数 + by_category + by_event） */
export async function fetchCertWarningSummary(
  params: { department?: string; cert_category?: string } = {},
) {
  return fetchApi<CertWarningSummary>(`/safety/cert-warnings/summary${buildQueryString(params)}`)
}

/** 回填持证复审/换证结果（闭环 → 进入下一证件周期） */
export async function renewCertificate(id: string, body: RenewRequest) {
  const response = await fetchApi<CertWarningDetail>(
    `/safety/cert-warnings/${id}/renew`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
  revalidatePath('/safety/cert-warnings')
  return response
}

// ============ 危化品库存 Actions（chemical-inventory） ============

/** 获取危化品库存台账（当前固定行，分页 + 部门/物料名称筛选） */
export async function fetchChemicalInventoryRecords(params: ChemicalInventoryQueryParams = {}) {
  return fetchApi<ChemicalInventoryRecord[]>(`/safety/chemical-inventory/records${buildQueryString(params)}`)
}

/** 获取当前库存风险统计 */
export async function fetchChemicalInventoryStats() {
  return fetchApi<ChemicalInventoryStats>('/safety/chemical-inventory/stats')
}

/** 手动全量风险扫描（回填风险标记/风险说明） */
export async function runChemicalInventoryScan() {
  const response = await fetchApi<ChemicalInventoryScanResult>(
    '/safety/chemical-inventory/scan',
    { method: 'POST' },
  )
  revalidatePath('/safety/chemical-inventory')
  return response
}

// ============ scheduler-config Actions（AI 配置 + 定时任务） ============

/** 获取 AI 配置总览（脱敏模型配置 + AI 调用功能清单） */
export async function fetchAiConfig() {
  return fetchApi<AiConfigData>(`${SAFETY_SCHEDULER_CONFIG}/ai-config`)
}

/** 更新单组模型配置（字段级部分更新；api_key 空=不改），成功写审计 + 失效缓存，调用后即时生效 */
export async function updateAiModelConfig(profile: AiModelProfile, data: UpdateAiConfigInput) {
  const response = await fetchApi<AiModelConfig>(
    `${SAFETY_SCHEDULER_CONFIG}/ai-config/${encodeURIComponent(profile)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) },
  )
  revalidatePath('/safety/system/ai-config')
  return response
}

/** AI 配置变更审计列表（append-only，最新在前，limit 1-200，可选按 profile 过滤） */
export async function fetchAiConfigAudits(params: { profile?: string; limit?: number } = {}) {
  return fetchApi<AiConfigAuditItem[]>(
    `${SAFETY_SCHEDULER_CONFIG}/ai-config/audits${buildQueryString(params)}`,
  )
}

/** 更新单场景配置（字段级部分更新：enabled/model_profile；未知场景 404；白名单外绑定 422）。成功写审计 + 失效缓存，调用后即时生效 */
export async function updateAiScenario(scenario: string, input: UpdateAiScenarioInput) {
  const response = await fetchApi<AiScenarioConfig>(
    `${SAFETY_SCHEDULER_CONFIG}/ai-scenarios/${encodeURIComponent(scenario)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) },
  )
  revalidatePath('/safety/system/ai-config')
  return response
}

/** 场景配置变更审计列表（append-only，最新在前，limit 1-200，可选按 scenario 过滤） */
export async function fetchAiScenarioAudits(params: { scenario?: string; limit?: number } = {}) {
  return fetchApi<AiScenarioAuditItem[]>(
    `${SAFETY_SCHEDULER_CONFIG}/ai-scenarios/audits${buildQueryString(params)}`,
  )
}

/** 连通性测试（只读：不写库不写审计；config 为空字段后端用当前生效配置） */
export async function testAiModelProfile(
  profile: AiModelProfile,
  config: Partial<UpdateAiConfigInput> = {},
) {
  return fetchApi<AiModelTestResult>(
    `${SAFETY_SCHEDULER_CONFIG}/ai-config/test`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile, config }),
    },
  )
}

/** 获取定时任务列表（代码默认 + DB 覆写 + 今日运行状态） */
export async function fetchScheduledTasks() {
  return fetchApi<ScheduledTask[]>(`${SAFETY_SCHEDULER_CONFIG}/tasks`)
}

/** 获取飞书机器人所在群聊列表（后端 5 分钟缓存） */
export async function fetchFeishuGroups() {
  return fetchApi<FeishuGroupsData>(`${SAFETY_SCHEDULER_CONFIG}/feishu/groups`)
}

/** 获取人员列表（发送对象-个人 DM 候选；已绑定 open_id 的用户） */
export async function fetchFeishuPersons() {
  return fetchApi<FeishuPerson[]>(`${SAFETY_SCHEDULER_CONFIG}/persons`)
}

/** 更新定时任务配置（发送对象/启停/执行时间），写审计 */
export async function updateScheduledTask(jobName: string, data: UpdateScheduledTaskInput) {
  const response = await fetchApi<ScheduledTask>(
    `${SAFETY_SCHEDULER_CONFIG}/tasks/${encodeURIComponent(jobName)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) },
  )
  revalidatePath('/safety/system/scheduled-tasks')
  return response
}

/** 预览任务报告（只读生成，不推送） */
export async function previewScheduledTask(jobName: string, date?: string) {
  return fetchApi<SchedulerPreviewData>(
    `${SAFETY_SCHEDULER_CONFIG}/tasks/${encodeURIComponent(jobName)}/preview`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ date }) },
  )
}

/** 手动触发任务一次（真实执行并推送目标群） */
export async function runScheduledTask(jobName: string) {
  return fetchApi<SchedulerRunResult>(
    `${SAFETY_SCHEDULER_CONFIG}/tasks/${encodeURIComponent(jobName)}/run`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) },
  )
  revalidatePath('/safety/system/scheduled-tasks')
}

// ============ bitable-config Actions（多维表格配置中心） ============

/** 域清单总览（14 域 + kind 连接/映射配置状态） */
export async function fetchBitableDomains() {
  return fetchApi<BitableDomainOverview[]>(`${SAFETY_BITABLE_CONFIG}/domains`)
}

/** 单域全部 kind 连接视图（含 disabled/missing 状态行） */
export async function fetchBitableConnection(domain: string) {
  return fetchApi<BitableConnection[]>(
    `${SAFETY_BITABLE_CONFIG}/connections/${encodeURIComponent(domain)}`,
  )
}

/** 更新连接（写审计 + 失效缓存 + 触发重订阅） */
export async function updateBitableConnection(
  domain: string,
  kind: string,
  data: UpdateBitableConnectionInput,
) {
  const response = await fetchApi<BitableConnection>(
    `${SAFETY_BITABLE_CONFIG}/connections/${encodeURIComponent(domain)}/${encodeURIComponent(kind)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) },
  )
  revalidatePath('/safety/system/bitable-config')
  return response
}

/** 读字段映射（DB 行优先，无行回退 registry 默认） */
export async function fetchBitableMappings(domain: string, kind: string) {
  return fetchApi<BitableMappingsView>(
    `${SAFETY_BITABLE_CONFIG}/mappings/${encodeURIComponent(domain)}/${encodeURIComponent(kind)}`,
  )
}

/** 全量替换字段映射（写审计 + 失效缓存） */
export async function updateBitableMappings(
  domain: string,
  kind: string,
  mappings: BitableFieldMapping[],
) {
  const response = await fetchApi<BitableMappingsView>(
    `${SAFETY_BITABLE_CONFIG}/mappings/${encodeURIComponent(domain)}/${encodeURIComponent(kind)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mappings }) },
  )
  revalidatePath('/safety/system/bitable-config')
  return response
}

/** 测试连接（只读拉表/字段校验，不写库不写审计） */
export async function testBitableConnection(appToken: string, tableId: string) {
  return fetchApi<BitableTestResult>(
    `${SAFETY_BITABLE_CONFIG}/test-connection`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_token: appToken, table_id: tableId }),
    },
  )
}

/** 变更审计列表（append-only，最新在前，limit 1-200） */
export async function fetchBitableAudits(domain?: string, limit = 50) {
  return fetchApi<BitableAuditItem[]>(
    `${SAFETY_BITABLE_CONFIG}/audits${buildQueryString({ domain, limit })}`,
  )
}

/** 手动重订阅（兜底，写 resubscribe 审计） */
export async function resubscribeBitable(domain: string) {
  const response = await fetchApi<BitableResubscribeResult>(
    `${SAFETY_BITABLE_CONFIG}/resubscribe/${encodeURIComponent(domain)}`,
    { method: 'POST' },
  )
  revalidatePath('/safety/system/bitable-config')
  return response
}

// ============ Info Query (RAG Chat) Actions ============
// 后端 POST /safety/knowledge/chat 存在，但安全侧 actions 里缺失此函数（合并时丢失），此处恢复。
// 类型 InfoQuerySource / InfoQueryResponse 从 '@/types/safety' 引入。

export async function queryKnowledgeChat(
  query: string,
  history?: { role: string; content: string }[],
) {
  return fetchApi<{
    answer: string
    sources: {
      doc_title: string
      article_ref: string
      chunk_text: string
      doc_category: string
      feishu_url: string
    }[]
  }>('/safety/knowledge/chat', {
    method: 'POST',
    body: JSON.stringify({ query, history: history || [] }),
  })
}
