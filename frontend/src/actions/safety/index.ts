'use server'

import { revalidatePath } from 'next/cache'
// 注意：以下 revalidatePath 调用指向的页面路径部分仍在开发中，待对应页面创建后将自动生效
import { getAuthHeaders } from '@/lib/auth'
import { fetchApi } from './_helpers'
import { API_BASE, buildQueryString, SAFETY_BITABLE_CONFIG, SAFETY_SCHEDULER_CONFIG, SAFETY_APP_CONFIG } from './_utils'
import type {
  AiAuditQueryParams,
  AiAuditStats,
  AiCallAuditDetail,
  AiCallAuditListItem,
  Contractor,
  ContractorFormData,
  ContractorWorkRecord,
  ContractorWorkRecordFormData,
  HazardReport,
  HazardReportQueryParams,
  HazardStats,
  OperationRegulation,
  OperationRegulationFormData,
  RegulationRevision,
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleQueryParams,
  KnowledgeCategoryCounts,
  VersionChainItem,
  SemanticSearchResult,
  SafetyTraining,
  SafetyTrainingFormData,
  SpecialOperationPermit,
  SpecialOperationPermitFormData,
  SpecialOperationPersonnel,
  SpecialOperationPersonnelFormData,
  SpecialOperationReport,
  SpecialOperationReportQueryParams,
  SpecialOperationLedgerQueryParams,
  SpecialOperationLedgerStats,
  KeyRiskOperationReport,
  KeyRiskOperationQueryParams,
  KeyRiskOperationLedgerStats,
  DailyReportRecord,
  DailyReportStats,
  TrainingRecord,
  ApiResponse,
  // contractor admission（相关方准入）
  ContractorAdmission,
  ContractorAdmissionListItem,
  ContractorAdmissionQueryParams,
  ContractorAdmissionStats,
  // fire alarm（消防报警分析）
  FireAlarmQueryParams,
  FireAlarmRecord,
  FireAlarmStats,
  // central alarm（中控报警分析）
  CentralAlarmQueryParams,
  CentralAlarmRecord,
  CentralAlarmStats,
  // occupational health（design §八：新 OH 函数统一 code===200，写操作后 revalidatePath）
  OhPerson,
  OhPersonQueryParams,
  OhPersonStats,
  OhHealthExam,
  OhHealthExamQueryParams,
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
  // knowledge
  AgentUsageStats,
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
  // chemical inventory（危化品库存）
  ChemicalInventoryRecord,
  ChemicalInventoryQueryParams,
  ChemicalInventoryStats,
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
  // app-config（应用配置中心，env→DB 迁移）
  AppConfigAuditItem,
  AppConfigItem,
  AppConfigListData,
  UpdateAppConfigInput,
  // accident / check / daily risk report / oh hazard monitor（迁移补齐）
  SafetyCheck,
  OhHazardMonitor,
  OhHazardMonitorQueryParams,
} from '@/types/safety'

// ============ HazardReport Actions ============

export async function fetchHazardStats() {
  return fetchApi<HazardStats>('/safety/hazards/stats')
}

// ============ Contractor Actions ============

// ============ SafetyTraining Actions ============

// ============ TrainingRecord Actions ============

// ============ Training Certificate Actions ============
// （旧 /safety/training-certificates/expiring 已随一期退役；证书预警走 lib/api/safety/cert-warning）

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

// ============ Hazard Identification AI Export ============

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

// ============ SOP Generator Actions ============

// ============ RegulationRevision Actions ============

// ============ SpecialOperationPersonnel Actions ============

export async function deletePersonnel(id: string) {
  const response = await fetchApi<null>(`/safety/special-operation-personnel/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/safety/special-ops-personnel')
  return response
}

// ============ SpecialOperationPermit Actions ============

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

// ── 版本管理 ──

export async function getArticleVersions(id: string) {
  return fetchApi<VersionChainItem[]>(`/safety/knowledge-articles/${id}/versions`)
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

// ── Agent 统计 ──

export async function getAgentUsageStats(articleId: string) {
  return fetchApi<AgentUsageStats>(`/safety/knowledge-articles/${articleId}/agent-stats`)
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
// （列表查询已迁 lib/api/safety/key-risk-operation（react-query）；此处保留详情/统计/同步）

export async function getKeyRiskOperationReport(id: string) {
  return fetchApi<KeyRiskOperationReport>(`/safety/key-risk-operation-reports/${id}`)
}

export async function getKeyRiskOperationStats() {
  return fetchApi<KeyRiskOperationLedgerStats>('/safety/key-risk-operation-reports/stats')
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


// ============ CentralAlarm Actions（中控报警分析） ============

export async function getCentralAlarmRecords(params: CentralAlarmQueryParams = {}) {
  return fetchApi<CentralAlarmRecord[]>(`/safety/central-alarms/records${buildQueryString(params)}`)
}

export async function getCentralAlarmStats() {
  return fetchApi<CentralAlarmStats>('/safety/central-alarms/stats')
}


// ============ EHS变更管理 (MOC) ============

// CRUD
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

export async function getOhApplicationStats() {
  return fetchApi<OhApplicationStats>('/safety/oh/applications/stats')
}

// ── 异常随访 oh/followups ──

export async function getOhFollowups(params: OhFollowupQueryParams = {}) {
  return fetchApi<OhFollowup[]>(`/safety/oh/followups${buildQueryString(params)}`)
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

export async function forgetAgentMemories() {
  const res = await fetchApi<{ deleted: number }>(`/safety/agent/memories/forget`, {
    method: 'POST',
  })
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

// ── 附件文档 ──

export async function getDrillDocuments(recordId: string) {
  return fetchApi<DrillDocument[]>(
    `/safety/emergency-drills/${recordId}/documents`,
  )
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

// ==================== MSDS Actions ====================

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

// ============ 危化品库存 Actions（chemical-inventory） ============

/** 获取危化品库存台账（当前固定行，分页 + 部门/物料名称筛选） */
export async function fetchChemicalInventoryRecords(params: ChemicalInventoryQueryParams = {}) {
  return fetchApi<ChemicalInventoryRecord[]>(`/safety/chemical-inventory/records${buildQueryString(params)}`)
}

/** 获取当前库存风险统计 */
export async function fetchChemicalInventoryStats() {
  return fetchApi<ChemicalInventoryStats>('/safety/chemical-inventory/stats')
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

// ============ app-config Actions（应用配置中心，env→DB 迁移） ============

/** 全部注册项生效视图（值/来源 env>db>default/冲突标记；secret 已脱敏） */
export async function fetchAppConfig() {
  return fetchApi<AppConfigListData>(SAFETY_APP_CONFIG)
}

/** 更新单键（写 DB + 审计 + 缓存失效；未知键 404 / 值非法 422） */
export async function updateAppConfig(key: string, input: UpdateAppConfigInput) {
  const response = await fetchApi<AppConfigItem>(
    `${SAFETY_APP_CONFIG}/${encodeURIComponent(key)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) },
  )
  revalidatePath('/safety/system/app-config')
  return response
}

/** 变更审计列表（key 可选过滤） */
export async function fetchAppConfigAudits(key?: string, limit = 50) {
  return fetchApi<AppConfigAuditItem[]>(
    `${SAFETY_APP_CONFIG}/audits${buildQueryString({ key, limit })}`,
  )
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

// ==================== 台账导出（Server Action 返回 base64，客户端下载） ====================

export async function exportSpecialOpsLedger(filters: Record<string, unknown>): Promise<{ blob: string; filename: string }> {
  const authHeaders = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/safety/special-operation-ledger/export`, {
    method: 'POST',
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify(filters),
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { blob: base64, filename: '特殊作业台账.xlsx' }
}

export async function parseSpecialOpsQuery(naturalQuery: string): Promise<{
  explanation?: string
  filters: Record<string, unknown>
}> {
  const authHeaders = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/safety/special-operation-ledger/parse-query`, {
    method: 'POST',
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify({ natural_query: naturalQuery }),
  })
  if (!res.ok) throw new Error('AI 解析失败')
  const json = await res.json()
  return { explanation: json.data?.explanation || '', filters: json.data || {} }
}

export async function exportKeyRiskOpsReports(filters: Record<string, unknown>): Promise<{ blob: string; filename: string }> {
  const authHeaders = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/safety/key-risk-operation-reports/export`, {
    method: 'POST',
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify(filters),
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { blob: base64, filename: '关键风险作业台账.xlsx' }
}


// ============ SafetyCheck Actions（安全检查） ============

export async function submitCheck(id: string) {
  const response = await fetchApi<SafetyCheck>(`/safety/checks/${id}/submit`, {
    method: 'POST',
  })
  revalidatePath('/safety/check')
  return response
}

// ============ Accident Actions（事故管理） ============

// ============ DailyRiskReport Actions（每日风险作业报备） ============

// ============ OhHazardMonitor Actions（职业危害因素监测） ============

export async function getOhHazardMonitors(params: OhHazardMonitorQueryParams = {}) {
  return fetchApi<OhHazardMonitor[]>(`/safety/oh-hazard-monitors${buildQueryString(params)}`)
}

export async function getOhHazardMonitor(id: string) {
  return fetchApi<OhHazardMonitor>(`/safety/oh-hazard-monitors/${id}`)
}
