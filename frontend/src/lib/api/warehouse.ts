// 仓储管理 API 请求函数
// Server Actions 用绝对 URL，客户端用相对 URL

import {
  LocationCreate,
  LocationRecord,
  LocationUpdate,
  MaterialCreate,
  MaterialFilter,
  MaterialRecord,
  MaterialUpdate,
  MovementCreate,
  MovementFilter,
  MovementPlanCreateInput,
  MovementPlanFilter,
  MovementPlanRecord,
  MovementRecord,
  Paginated,
  StockFilter,
  StockRecord,
  StocktakeCreate,
  StocktakeRecord,
  StocktakeUpdate,
  WarehouseAiAuditDetail,
  WarehouseAiAuditListParams,
  WarehouseAiAuditListItem,
  WarehouseAiAuditStats,
  WarehouseAiModelAuditItem,
  WarehouseAiModelTestResult,
  WarehouseAiModelUpdateInput,
  WarehouseAiModelView,
  WarehouseAiModelsData,
  WarehouseAiScenarioAuditItem,
  WarehouseAiScenarioUpdateInput,
  WarehouseAiScenarioView,
  WarehouseAiScenariosData,
  WarehouseBitableAuditItem,
  WarehouseBitableData,
  WarehouseBitableRefreshResult,
  WarehouseBitableTestResult,
  WarehouseBitableUpdateInput,
  WarehouseBitableView,
  WarehouseConfigAuditKind,
  WarehouseRuntimeAuditItem,
  WarehouseRuntimeData,
  WarehouseRuntimeValue,
  WarehouseRuntimeView,
  WarehouseSchedulerAuditItem,
  WarehouseSchedulerData,
  WarehouseSchedulerTaskView,
  WarehouseSchedulerUpdateInput,
  WarehousePushTaskAuditItem,
  WarehousePushTaskData,
  WarehousePushTaskUpdateInput,
  WarehousePushTaskView,
  WarehousePushTriggerResult,
  WarehousePushLogEntry,
  WarehouseOverview,
  DashboardSummary,
  MovementTrendPoint,
  StockDistribution,
  LowStockTop,
  DashboardTodos,
  StockStatus,
} from '@/types/warehouse'
import { apiDelete, apiGet, apiPost, apiPut, apiFetchPaginated } from '@/lib/http-client'

const SERVER_API = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
/** 浏览器端 API base：优先 NEXT_PUBLIC_API_BASE_URL（直连后端）；
 *  未配置时回退相对路径（开发走 next.config rewrites，生产需在构建时配置该变量）。 */
const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''
const BASE = '/api/v1/warehouse'

// ── 驾驶舱（V2.0 分期A）──

export async function fetchDashboardSummaryClient(): Promise<DashboardSummary> {
  return apiGet<DashboardSummary>(`${CLIENT_API}${BASE}/dashboard/summary`)
}

export async function fetchMovementTrendClient(days = 30): Promise<MovementTrendPoint[]> {
  return apiGet<MovementTrendPoint[]>(`${CLIENT_API}${BASE}/dashboard/movement-trend?days=${days}`)
}

export async function fetchStockDistributionClient(): Promise<StockDistribution> {
  return apiGet<StockDistribution>(`${CLIENT_API}${BASE}/dashboard/stock-distribution`)
}

export async function fetchLowStockTopClient(limit = 10): Promise<LowStockTop> {
  return apiGet<LowStockTop>(`${CLIENT_API}${BASE}/dashboard/low-stock-top?limit=${limit}`)
}

export async function fetchDashboardTodosClient(): Promise<DashboardTodos> {
  return apiGet<DashboardTodos>(`${CLIENT_API}${BASE}/dashboard/todos`)
}

// ── 出入库计划单（V2.0 分期A） ──

export async function fetchPlansClient(
  params: MovementPlanFilter = {},
): Promise<Paginated<MovementPlanRecord>> {
  const sp = new URLSearchParams()
  if (params.direction) sp.set('direction', params.direction)
  if (params.status) sp.set('status', params.status)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiFetchPaginated<MovementPlanRecord>(`${CLIENT_API}${BASE}/plans${qs ? `?${qs}` : ''}`)
}

export async function createPlan(payload: MovementPlanCreateInput): Promise<MovementPlanRecord> {
  return apiPost<MovementPlanRecord>(`${SERVER_API}${BASE}/plans`, payload)
}

export async function startPlan(planId: string): Promise<MovementPlanRecord> {
  return apiPost<MovementPlanRecord>(`${SERVER_API}${BASE}/plans/${planId}/start`, {})
}

export async function cancelPlan(planId: string, reason: string): Promise<MovementPlanRecord> {
  return apiPost<MovementPlanRecord>(`${SERVER_API}${BASE}/plans/${planId}/cancel`, { reason })
}

export async function generatePlanMovement(
  planId: string,
  payload: { quantity?: number; remark?: string | null } = {},
): Promise<{ plan: MovementPlanRecord; movement: MovementRecord }> {
  return apiPost<{ plan: MovementPlanRecord; movement: MovementRecord }>(
    `${SERVER_API}${BASE}/plans/${planId}/movement`,
    payload,
  )
}

// ── 概览 ──

export async function fetchWarehouseOverview(): Promise<WarehouseOverview> {
  return apiGet<WarehouseOverview>(`${SERVER_API}${BASE}/overview`)
}

// ── 物料主数据 ──

function setMaterialParams(sp: URLSearchParams, params: MaterialFilter) {
  if (params.category) sp.set('category', params.category)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchMaterials(params: MaterialFilter = {}): Promise<Paginated<MaterialRecord>> {
  const sp = new URLSearchParams()
  setMaterialParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MaterialRecord>(`${SERVER_API}${BASE}/materials${qs ? `?${qs}` : ''}`)
}

export async function fetchMaterialsClient(
  params: MaterialFilter = {}
): Promise<Paginated<MaterialRecord>> {
  const sp = new URLSearchParams()
  setMaterialParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MaterialRecord>(`${CLIENT_API}${BASE}/materials${qs ? `?${qs}` : ''}`)
}

export async function createMaterial(data: MaterialCreate): Promise<MaterialRecord> {
  return apiPost<MaterialRecord>(`${SERVER_API}${BASE}/materials`, data)
}

export async function updateMaterial(id: string, data: MaterialUpdate): Promise<MaterialRecord> {
  return apiPut<MaterialRecord>(`${SERVER_API}${BASE}/materials/${id}`, data)
}

export async function deleteMaterial(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/materials/${id}`)
}

// ── 库位 ──

export async function fetchLocations(): Promise<LocationRecord[]> {
  return apiGet<LocationRecord[]>(`${SERVER_API}${BASE}/locations`)
}

export async function fetchLocationsClient(): Promise<LocationRecord[]> {
  return apiGet<LocationRecord[]>(`${CLIENT_API}${BASE}/locations`)
}

export async function createLocation(data: LocationCreate): Promise<LocationRecord> {
  return apiPost<LocationRecord>(`${SERVER_API}${BASE}/locations`, data)
}

export async function updateLocation(id: string, data: LocationUpdate): Promise<LocationRecord> {
  return apiPut<LocationRecord>(`${SERVER_API}${BASE}/locations/${id}`, data)
}

export async function deleteLocation(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/locations/${id}`)
}

// ── 库存 ──

function setStockParams(sp: URLSearchParams, params: StockFilter) {
  if (params.batch_no) sp.set("batch_no", params.batch_no)
  if (params.expiry_from) sp.set("expiry_from", params.expiry_from)
  if (params.expiry_to) sp.set("expiry_to", params.expiry_to)
  if (params.category) sp.set('category', params.category)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.location_id) sp.set('location_id', params.location_id)
  if (params.status) sp.set('status', params.status)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchStocks(params: StockFilter = {}): Promise<Paginated<StockRecord>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<StockRecord>(`${SERVER_API}${BASE}/stocks${qs ? `?${qs}` : ''}`)
}

export async function fetchStocksClient(params: StockFilter = {}): Promise<Paginated<StockRecord>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<StockRecord>(`${CLIENT_API}${BASE}/stocks${qs ? `?${qs}` : ''}`)
}

// ── 出入库 ──

function setMovementParams(sp: URLSearchParams, params: MovementFilter) {
  if (params.material_id) sp.set('material_id', params.material_id)
  if (params.direction) sp.set('direction', params.direction)
  if (params.source_type) sp.set('source_type', params.source_type)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.location_id) sp.set('location_id', params.location_id)
  if (params.occurred_from) sp.set('occurred_from', params.occurred_from)
  if (params.occurred_to) sp.set('occurred_to', params.occurred_to)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchMovements(
  params: MovementFilter = {}
): Promise<Paginated<MovementRecord>> {
  const sp = new URLSearchParams()
  setMovementParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MovementRecord>(`${SERVER_API}${BASE}/movements${qs ? `?${qs}` : ''}`)
}

export async function fetchMovementsClient(
  params: MovementFilter = {}
): Promise<Paginated<MovementRecord>> {
  const sp = new URLSearchParams()
  setMovementParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MovementRecord>(`${CLIENT_API}${BASE}/movements${qs ? `?${qs}` : ''}`)
}

export async function createMovement(data: MovementCreate): Promise<MovementRecord> {
  return apiPost<MovementRecord>(`${SERVER_API}${BASE}/movements`, data)
}

export async function deleteMovement(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/movements/${id}`)
}

// ── 库存状态机（分期D Ticket 03）──

export interface StockStatusChange {
  old_status: StockStatus
  new_status: StockStatus
}

export async function changeStockStatus(
  stockId: string,
  data: { new_status: StockStatus; reason?: string },
): Promise<StockStatusChange> {
  return apiPost<StockStatusChange>(
    `${SERVER_API}${BASE}/stocks/${encodeURIComponent(stockId)}/status`,
    { reason: '', ...data },
  )
}

// ── 盘点 ──

export async function fetchStocktakes(
  params: { page?: number; page_size?: number; status?: string } = {}
): Promise<Paginated<StocktakeRecord>> {
  const sp = new URLSearchParams()
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  if (params.status) sp.set('status', params.status)
  const qs = sp.toString()
  return apiFetchPaginated<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes${qs ? `?${qs}` : ''}`)
}

export async function fetchStocktake(id: string): Promise<StocktakeRecord> {
  return apiGet<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}`)
}

export async function fetchStocktakeClient(id: string): Promise<StocktakeRecord> {
  return apiGet<StocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${id}`)
}

export async function fetchStocktakesClient(
  params: { page?: number; page_size?: number; status?: string } = {}
): Promise<Paginated<StocktakeRecord>> {
  const sp = new URLSearchParams()
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  if (params.status) sp.set('status', params.status)
  const qs = sp.toString()
  return apiFetchPaginated<StocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes${qs ? `?${qs}` : ''}`)
}

export async function createStocktake(data: StocktakeCreate): Promise<StocktakeRecord> {
  return apiPost<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes`, data)
}

export async function updateStocktake(
  id: string,
  data: StocktakeUpdate
): Promise<StocktakeRecord> {
  return apiPut<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}`, data)
}

export async function confirmStocktake(id: string): Promise<StocktakeRecord> {
  return apiPost<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}/confirm`)
}

export async function deleteStocktake(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/stocktakes/${id}`)
}

// ═══════════════════════════════════════════════════════════════
// 系统配置中心（backend system_config_api.py，tickets 08+09）
// 统一响应包 {code,message,data,meta}：apiGet/apiPut 解包 data，非 2xx 抛
// Error（message 为后端中文可读错误）。GET 供 Server Actions 包装；
// PUT/POST 低层封装仅供 actions/warehouse.ts 调用（写操作走 Server Actions）。
// ═══════════════════════════════════════════════════════════════

const SC_BASE = `${BASE}/system-config`

function encode(v: string): string {
  return encodeURIComponent(v)
}

// ── AI 模型配置 ──

export async function fetchWarehouseAiModels(): Promise<WarehouseAiModelsData> {
  return apiGet<WarehouseAiModelsData>(`${SERVER_API}${SC_BASE}/ai-models`)
}

export async function fetchWarehouseAiModelAudits(limit = 50): Promise<WarehouseAiModelAuditItem[]> {
  const data = await apiGet<{ audits: WarehouseAiModelAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/ai-models/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehouseAiModel(
  profile: string,
  data: WarehouseAiModelUpdateInput,
): Promise<WarehouseAiModelView> {
  return apiPut<WarehouseAiModelView>(`${SERVER_API}${SC_BASE}/ai-models/${encode(profile)}`, data)
}

export async function testWarehouseAiModel(profile: string): Promise<WarehouseAiModelTestResult> {
  return apiPost<WarehouseAiModelTestResult>(`${SERVER_API}${SC_BASE}/ai-models/test`, { profile })
}

// ── AI 场景配置 ──

export async function fetchWarehouseAiScenarios(): Promise<WarehouseAiScenariosData> {
  return apiGet<WarehouseAiScenariosData>(`${SERVER_API}${SC_BASE}/ai-scenarios`)
}

export async function fetchWarehouseAiScenarioAudits(
  limit = 50,
): Promise<WarehouseAiScenarioAuditItem[]> {
  const data = await apiGet<{ audits: WarehouseAiScenarioAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/ai-scenarios/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehouseAiScenario(
  scenario: string,
  input: WarehouseAiScenarioUpdateInput,
): Promise<WarehouseAiScenarioView> {
  return apiPut<WarehouseAiScenarioView>(
    `${SERVER_API}${SC_BASE}/ai-scenarios/${encode(scenario)}`,
    input,
  )
}

// ── 运行参数 ──

export async function fetchWarehouseRuntimeConfigs(): Promise<WarehouseRuntimeData> {
  return apiGet<WarehouseRuntimeData>(`${SERVER_API}${SC_BASE}/runtime`)
}

export async function fetchWarehouseRuntimeAudits(limit = 50): Promise<WarehouseRuntimeAuditItem[]> {
  const data = await apiGet<{ audits: WarehouseRuntimeAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/runtime/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehouseRuntimeConfig(
  key: string,
  value: WarehouseRuntimeValue,
): Promise<WarehouseRuntimeView> {
  return apiPut<WarehouseRuntimeView>(`${SERVER_API}${SC_BASE}/runtime/${encode(key)}`, { value })
}

// ── 多维表格连接 ──

export async function fetchWarehouseBitableConnections(): Promise<WarehouseBitableData> {
  return apiGet<WarehouseBitableData>(`${SERVER_API}${SC_BASE}/bitable/connections`)
}

export async function fetchWarehouseBitableAudits(limit = 50): Promise<WarehouseBitableAuditItem[]> {
  const data = await apiGet<{ audits: WarehouseBitableAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/bitable/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehouseBitableConnection(
  tableKey: string,
  input: WarehouseBitableUpdateInput,
): Promise<WarehouseBitableView> {
  return apiPut<WarehouseBitableView>(
    `${SERVER_API}${SC_BASE}/bitable/connections/${encode(tableKey)}`,
    input,
  )
}

export async function testWarehouseBitableConnection(
  tableKey: string,
): Promise<WarehouseBitableTestResult> {
  return apiPost<WarehouseBitableTestResult>(`${SERVER_API}${SC_BASE}/bitable/test-connection`, {
    table_key: tableKey,
  })
}

export async function refreshWarehouseBitableFields(
  tableKey: string,
): Promise<WarehouseBitableRefreshResult> {
  return apiPost<WarehouseBitableRefreshResult>(
    `${SERVER_API}${SC_BASE}/bitable/refresh-fields/${encode(tableKey)}`,
  )
}

// ── 多维表格环境坐标组（V3.0 分期D §3.3 生产版切换准备）──

export async function fetchWarehouseBitableEnvMode(): Promise<string> {
  const data = await apiGet<{ mode: string }>(`${SERVER_API}${SC_BASE}/bitable/env-mode`)
  return data?.mode ?? 'test'
}

export async function putWarehouseBitableEnvMode(mode: string): Promise<string> {
  const data = await apiPut<{ mode: string }>(`${SERVER_API}${SC_BASE}/bitable/env-mode`, { mode })
  return data?.mode ?? mode
}

export async function fetchWarehouseBitableEnvConnections(
  env: string,
): Promise<WarehouseBitableData> {
  return apiGet<WarehouseBitableData>(
    `${SERVER_API}${SC_BASE}/bitable/env-connections/${encode(env)}`,
  )
}

export async function putWarehouseBitableEnvConnection(
  env: string,
  tableKey: string,
  input: WarehouseBitableUpdateInput,
): Promise<WarehouseBitableView> {
  return apiPut<WarehouseBitableView>(
    `${SERVER_API}${SC_BASE}/bitable/env-connections/${encode(env)}/${encode(tableKey)}`,
    input,
  )
}

// ── 定时任务 / 告警目标 ──

export async function fetchWarehouseSchedulerTasks(): Promise<WarehouseSchedulerData> {
  return apiGet<WarehouseSchedulerData>(`${SERVER_API}${SC_BASE}/scheduler-tasks`)
}

export async function fetchWarehouseSchedulerAudits(
  limit = 50,
): Promise<WarehouseSchedulerAuditItem[]> {
  const data = await apiGet<{ audits: WarehouseSchedulerAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/scheduler-tasks/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehouseSchedulerTask(
  jobName: string,
  input: WarehouseSchedulerUpdateInput,
): Promise<WarehouseSchedulerTaskView> {
  return apiPut<WarehouseSchedulerTaskView>(
    `${SERVER_API}${SC_BASE}/scheduler-tasks/${encode(jobName)}`,
    input,
  )
}

// ── 推送任务（V3.0 分期A 推送订阅中心）──

export async function fetchWarehousePushTasks(): Promise<WarehousePushTaskData> {
  return apiGet<WarehousePushTaskData>(`${SERVER_API}${SC_BASE}/push-tasks`)
}

export async function fetchWarehousePushTaskAudits(
  limit = 50,
): Promise<WarehousePushTaskAuditItem[]> {
  const data = await apiGet<{ audits: WarehousePushTaskAuditItem[] }>(
    `${SERVER_API}${SC_BASE}/push-tasks/audits?limit=${limit}`,
  )
  return data?.audits ?? []
}

export async function putWarehousePushTask(
  taskName: string,
  input: WarehousePushTaskUpdateInput,
): Promise<WarehousePushTaskView> {
  return apiPut<WarehousePushTaskView>(
    `${SERVER_API}${SC_BASE}/push-tasks/${encode(taskName)}`,
    input,
  )
}

export async function triggerWarehousePushTask(
  taskName: string,
  dryRun = false,
): Promise<WarehousePushTriggerResult> {
  return apiPost<WarehousePushTriggerResult>(
    `${SERVER_API}${SC_BASE}/push-tasks/${encode(taskName)}/trigger`,
    { dry_run: dryRun },
  )
}

export async function fetchWarehousePushLogs(
  params: { task_name?: string; status?: string; page?: number; page_size?: number } = {},
): Promise<Paginated<WarehousePushLogEntry>> {
  const sp = new URLSearchParams()
  if (params.task_name) sp.set('task_name', params.task_name)
  if (params.status) sp.set('status', params.status)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiFetchPaginated<WarehousePushLogEntry>(
    `${SERVER_API}${SC_BASE}/push-logs${qs ? `?${qs}` : ''}`,
  )
}

// ── AI 调用审计（/warehouse/ai-audits）──

function setAiAuditParams(sp: URLSearchParams, params: WarehouseAiAuditListParams) {
  if (params.scenario) sp.set('scenario', params.scenario)
  if (params.status) sp.set('status', params.status)
  if (params.trace_id) sp.set('trace_id', params.trace_id.trim())
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchWarehouseAiAudits(
  params: WarehouseAiAuditListParams = {},
): Promise<Paginated<WarehouseAiAuditListItem>> {
  const sp = new URLSearchParams()
  setAiAuditParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<WarehouseAiAuditListItem>(
    `${SERVER_API}${BASE}/ai-audits${qs ? `?${qs}` : ''}`,
  )
}

export async function fetchWarehouseAiAuditStats(params: { days?: number } = {}): Promise<WarehouseAiAuditStats> {
  const qs = params.days ? `?days=${params.days}` : ''
  return apiGet<WarehouseAiAuditStats>(`${SERVER_API}${BASE}/ai-audits/stats${qs}`)
}

export async function fetchWarehouseAiAuditDetail(id: string): Promise<WarehouseAiAuditDetail> {
  return apiGet<WarehouseAiAuditDetail>(`${SERVER_API}${BASE}/ai-audits/${encode(id)}`)
}

/** 六类配置变更审计取数分发（ConfigAuditSection 用；行为对应端点的 audits[]） */
export async function fetchWarehouseConfigAudits(
  kind: WarehouseConfigAuditKind,
  limit = 50,
): Promise<unknown[]> {
  switch (kind) {
    case 'ai-model':
      return fetchWarehouseAiModelAudits(limit)
    case 'ai-scenario':
      return fetchWarehouseAiScenarioAudits(limit)
    case 'runtime':
      return fetchWarehouseRuntimeAudits(limit)
    case 'bitable':
      return fetchWarehouseBitableAudits(limit)
    case 'scheduler':
      return fetchWarehouseSchedulerAudits(limit)
    case 'push':
      return fetchWarehousePushTaskAudits(limit)
  }
}
