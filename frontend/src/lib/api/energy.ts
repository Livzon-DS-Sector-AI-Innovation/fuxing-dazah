import {
  EnergyDeviceConfig,
  CreateDeviceInput,
  UpdateDeviceInput,
  DeviceQueryParams,
  EquipmentOption,
  EnergyData,
  EnergyDataHistory,
  DataQueryParams,
  HistoryQueryParams,
  CollectLog,
  CollectLogDetail,
  CollectSettings,
  LogQueryParams,
  PaginatedResponse,
  AlertRule,
  CreateRuleInput,
  UpdateRuleInput,
  RuleQueryParams,
  AlertRecord,
  ProcessRecordInput,
  RecordQueryParams,
  EnergyTypeConfig,
  CreateTypeConfigInput,
  UpdateTypeConfigInput,
  EnergyOverview,
  WorkshopConfig,
  CreateWorkshopConfigInput,
  UpdateWorkshopConfigInput,
  EnergyPersonnelCandidate,
  AlertRuleCandidate,
  WorkshopOption,
  DailyPushConfig,
  CreateDailyPushConfigInput,
  UpdateDailyPushConfigInput,
  DailyReportSendRequest,
  NitrogenPushConfig,
  CreateNitrogenPushConfigInput,
  UpdateNitrogenPushConfigInput,
  NitrogenReportSendRequest,
} from '@/types/energy'
import { apiGet, apiPost, apiPut, apiDelete, apiFetchPaginated } from '@/lib/http-client'

// Server Actions 调用后端用绝对 URL，客户端调用用相对 URL（经 Next.js rewrites 代理）
const SERVER_API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'
// 客户端调用优先使用 NEXT_PUBLIC_API_BASE_URL（Docker 构建时注入），
// 未配置时回退为空字符串走 Next.js rewrites 代理（本地开发）。
const CLIENT_API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || ''

// ── 平台信息 ──
export interface PlatformInfo {
  code: string
  name: string
}

export async function fetchPlatforms(): Promise<PlatformInfo[]> {
  return apiGet<PlatformInfo[]>(`${SERVER_API_BASE}/api/v1/energy/platforms`)
}

export async function fetchPlatformsClient(): Promise<PlatformInfo[]> {
  return apiGet<PlatformInfo[]>(`${CLIENT_API_BASE}/api/v1/energy/platforms`)
}

export async function fetchEquipmentOptionsClient(
  params: { keyword?: string; ids?: string } = {}
): Promise<EquipmentOption[]> {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.ids) searchParams.set('ids', params.ids)
  const qs = searchParams.toString()
  return apiGet<EquipmentOption[]>(
    `${CLIENT_API_BASE}/api/v1/energy/equipment-options${qs ? `?${qs}` : ''}`
  )
}

// ── 数据源配置（Server Actions）──

export async function fetchEnergyDevices(
  params: DeviceQueryParams = {}
): Promise<PaginatedResponse<EnergyDeviceConfig>> {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  if (params.is_enabled !== undefined) searchParams.set('is_enabled', String(params.is_enabled))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<EnergyDeviceConfig>(
    `${SERVER_API_BASE}/api/v1/energy/devices?${searchParams.toString()}`
  )
}

export async function fetchEnergyDeviceById(id: string): Promise<EnergyDeviceConfig> {
  return apiGet<EnergyDeviceConfig>(`${SERVER_API_BASE}/api/v1/energy/devices/${id}`)
}

export async function createEnergyDevice(
  data: CreateDeviceInput
): Promise<EnergyDeviceConfig> {
  return apiPost<EnergyDeviceConfig>(`${SERVER_API_BASE}/api/v1/energy/devices`, data)
}

export async function updateEnergyDevice(
  id: string,
  data: UpdateDeviceInput
): Promise<EnergyDeviceConfig> {
  return apiPut<EnergyDeviceConfig>(`${SERVER_API_BASE}/api/v1/energy/devices/${id}`, data)
}

export async function deleteEnergyDevice(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/devices/${id}`)
}

// ── 能耗数据（Server Actions）──

export async function fetchEnergyData(
  params: DataQueryParams = {}
): Promise<PaginatedResponse<EnergyData>> {
  const searchParams = new URLSearchParams()
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  if (params.device_id) searchParams.set('device_id', params.device_id)
  if (params.start_time) searchParams.set('start_time', params.start_time)
  if (params.end_time) searchParams.set('end_time', params.end_time)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<EnergyData>(
    `${SERVER_API_BASE}/api/v1/energy/data?${searchParams.toString()}`
  )
}

// ── 采集历史（Server Actions）──

export async function fetchEnergyDataHistory(
  params: HistoryQueryParams = {}
): Promise<PaginatedResponse<EnergyDataHistory>> {
  const searchParams = new URLSearchParams()
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  if (params.device_config_id) searchParams.set('device_config_id', params.device_config_id)
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.granularity) searchParams.set('granularity', params.granularity)
  if (params.start_time) searchParams.set('start_time', params.start_time)
  if (params.end_time) searchParams.set('end_time', params.end_time)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<EnergyDataHistory>(
    `${SERVER_API_BASE}/api/v1/energy/data/history?${searchParams.toString()}`
  )
}

export async function updateEnergyDataValue(
  dataId: string,
  value: number,
): Promise<void> {
  await apiPut(`${SERVER_API_BASE}/api/v1/energy/data/${dataId}`, { value })
}

// ── 数据采集（Server Actions）──

export async function triggerCollect(
  platformCode?: string
): Promise<{ message: string }> {
  return apiPost<{ message: string }>(
    `${SERVER_API_BASE}/api/v1/energy/collect/trigger`,
    { platform_code: platformCode ?? null }
  )
}

export async function fetchCollectLogs(
  params: LogQueryParams = {}
): Promise<PaginatedResponse<CollectLog>> {
  const searchParams = new URLSearchParams()
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.status) searchParams.set('status', params.status)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<CollectLog>(
    `${SERVER_API_BASE}/api/v1/energy/collect/logs?${searchParams.toString()}`
  )
}

export async function fetchCollectLogDetail(
  id: string
): Promise<CollectLogDetail> {
  return apiGet<CollectLogDetail>(
    `${SERVER_API_BASE}/api/v1/energy/collect/logs/${id}/detail`
  )
}

export async function clearCollectLogs(): Promise<{ deleted_count: number }> {
  return apiDelete<{ deleted_count: number }>(
    `${SERVER_API_BASE}/api/v1/energy/collect/logs`
  )
}

// ── 自动采集设置 ──

export async function fetchCollectSettings(): Promise<CollectSettings> {
  return apiGet<CollectSettings>(
    `${SERVER_API_BASE}/api/v1/energy/collect/settings`
  )
}

export async function updateCollectSettings(
  data: Partial<CollectSettings>
): Promise<CollectSettings> {
  return apiPut<CollectSettings>(
    `${SERVER_API_BASE}/api/v1/energy/collect/settings`,
    data
  )
}

// ── 客户端 API（React Query / 浏览器直接调用，相对路径走 Next.js rewrites）──

export async function fetchEnergyDevicesClient(
  params: DeviceQueryParams = {}
): Promise<PaginatedResponse<EnergyDeviceConfig>> {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  if (params.is_enabled !== undefined) searchParams.set('is_enabled', String(params.is_enabled))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<EnergyDeviceConfig>(
    `${CLIENT_API_BASE}/api/v1/energy/devices?${searchParams.toString()}`
  )
}

export async function fetchEnergyDataClient(
  params: DataQueryParams = {}
): Promise<PaginatedResponse<EnergyData>> {
  const searchParams = new URLSearchParams()
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  if (params.device_id) searchParams.set('device_id', params.device_id)
  if (params.start_time) searchParams.set('start_time', params.start_time)
  if (params.end_time) searchParams.set('end_time', params.end_time)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<EnergyData>(
    `${CLIENT_API_BASE}/api/v1/energy/data?${searchParams.toString()}`
  )
}

export async function fetchCollectLogDetailClient(
  id: string
): Promise<CollectLogDetail> {
  return apiGet<CollectLogDetail>(
    `${CLIENT_API_BASE}/api/v1/energy/collect/logs/${id}/detail`
  )
}

export async function fetchCollectLogsClient(
  params: LogQueryParams = {}
): Promise<PaginatedResponse<CollectLog>> {
  const searchParams = new URLSearchParams()
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.status) searchParams.set('status', params.status)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<CollectLog>(
    `${CLIENT_API_BASE}/api/v1/energy/collect/logs?${searchParams.toString()}`
  )
}


// ── 预警规则（Server Actions）──

export async function fetchAlertRules(
  params: RuleQueryParams = {}
): Promise<PaginatedResponse<AlertRule>> {
  const searchParams = new URLSearchParams()
  if (params.energy_type) searchParams.set('energy_type', String(params.energy_type))
  if (params.alert_level) searchParams.set('alert_level', String(params.alert_level))
  if (params.is_enabled !== undefined) searchParams.set('is_enabled', String(params.is_enabled))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<AlertRule>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/rules?${searchParams.toString()}`
  )
}

export async function fetchAlertRuleById(id: string): Promise<AlertRule> {
  return apiGet<AlertRule>(`${SERVER_API_BASE}/api/v1/energy/alerts/rules/${id}`)
}

export async function createAlertRule(data: CreateRuleInput): Promise<AlertRule> {
  return apiPost<AlertRule>(`${SERVER_API_BASE}/api/v1/energy/alerts/rules`, data)
}

export async function updateAlertRule(id: string, data: UpdateRuleInput): Promise<AlertRule> {
  return apiPut<AlertRule>(`${SERVER_API_BASE}/api/v1/energy/alerts/rules/${id}`, data)
}

export async function deleteAlertRule(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/alerts/rules/${id}`)
}

// ── 预警记录（Server Actions）──

export async function fetchAlertRecords(
  params: RecordQueryParams = {}
): Promise<PaginatedResponse<AlertRecord>> {
  const searchParams = new URLSearchParams()
  if (params.energy_type) searchParams.set('energy_type', String(params.energy_type))
  if (params.alert_level) searchParams.set('alert_level', String(params.alert_level))
  if (params.status) searchParams.set('status', String(params.status))
  if (params.start_time) searchParams.set('start_time', String(params.start_time))
  if (params.end_time) searchParams.set('end_time', String(params.end_time))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<AlertRecord>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/records?${searchParams.toString()}`
  )
}

export async function processAlertRecord(
  id: string,
  data: ProcessRecordInput
): Promise<AlertRecord> {
  return apiPut<AlertRecord>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/records/${id}/process`,
    data
  )
}

// ── 预警处理（车间预警审核）──

export async function fetchAlertProcessList(
  params: { status?: string; page?: number; page_size?: number } = {}
): Promise<PaginatedResponse<AlertRecord>> {
  const searchParams = new URLSearchParams()
  if (params.status) searchParams.set('status', String(params.status))
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<AlertRecord>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/process?${searchParams.toString()}`
  )
}

export async function fillAlertReason(
  id: string,
  data: { reason: string }
): Promise<AlertRecord> {
  return apiPut<AlertRecord>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/process/${id}/reason`,
    data
  )
}

export async function approveAlertRecord(id: string): Promise<void> {
  await apiPut(`${SERVER_API_BASE}/api/v1/energy/alerts/process/${id}/approve`)
}

export async function rejectAlertRecord(id: string): Promise<AlertRecord> {
  return apiPut<AlertRecord>(
    `${SERVER_API_BASE}/api/v1/energy/alerts/process/${id}/reject`
  )
}

// ── 能源类型配置 ──

export async function fetchTypeConfigs(
  isEnabled?: boolean
): Promise<PaginatedResponse<EnergyTypeConfig>> {
  const searchParams = new URLSearchParams()
  if (isEnabled !== undefined) searchParams.set('is_enabled', String(isEnabled))
  return apiFetchPaginated<EnergyTypeConfig>(
    `${SERVER_API_BASE}/api/v1/energy/type-configs?${searchParams.toString()}`
  )
}

export async function fetchEnabledTypeConfigsClient(): Promise<EnergyTypeConfig[]> {
  const res = await apiGet<{ data: EnergyTypeConfig[] }>(
    `${CLIENT_API_BASE}/api/v1/energy/type-configs/enabled`
  )
  return (res as any).data ?? (res as any)
}

export async function createTypeConfig(
  data: CreateTypeConfigInput
): Promise<EnergyTypeConfig> {
  return apiPost<EnergyTypeConfig>(
    `${SERVER_API_BASE}/api/v1/energy/type-configs`,
    data
  )
}

export async function updateTypeConfig(
  id: string,
  data: UpdateTypeConfigInput
): Promise<EnergyTypeConfig> {
  return apiPut<EnergyTypeConfig>(
    `${SERVER_API_BASE}/api/v1/energy/type-configs/${id}`,
    data
  )
}

export async function deleteTypeConfig(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/type-configs/${id}`)
}

// ── 能源总览 ──

export interface OverviewParams {
  start_time: string
  end_time: string
  energy_type?: string
  granularity?: 'hourly' | 'daily'
}

export async function fetchEnergyOverview(params: OverviewParams): Promise<EnergyOverview> {
  const searchParams = new URLSearchParams()
  searchParams.set('start_time', params.start_time)
  searchParams.set('end_time', params.end_time)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  searchParams.set('granularity', params.granularity || 'daily')
  return apiGet<EnergyOverview>(
    `${CLIENT_API_BASE}/api/v1/energy/overview?${searchParams.toString()}`
  )
}

// ── 车间预警配置（Server Actions）──

export async function fetchWorkshopConfigs(
  page = 1,
  pageSize = 20,
  isEnabled?: boolean,
): Promise<PaginatedResponse<WorkshopConfig>> {
  const searchParams = new URLSearchParams()
  searchParams.set('page', String(page))
  searchParams.set('page_size', String(pageSize))
  if (isEnabled !== undefined) searchParams.set('is_enabled', String(isEnabled))
  return apiFetchPaginated<WorkshopConfig>(
    `${SERVER_API_BASE}/api/v1/energy/workshop-configs?${searchParams.toString()}`
  )
}

export async function fetchWorkshopConfigById(id: string): Promise<WorkshopConfig> {
  return apiGet<WorkshopConfig>(`${SERVER_API_BASE}/api/v1/energy/workshop-configs/${id}`)
}

export async function createWorkshopConfig(
  data: CreateWorkshopConfigInput
): Promise<WorkshopConfig> {
  return apiPost<WorkshopConfig>(`${SERVER_API_BASE}/api/v1/energy/workshop-configs`, data)
}

export async function updateWorkshopConfig(
  id: string,
  data: UpdateWorkshopConfigInput
): Promise<WorkshopConfig> {
  return apiPut<WorkshopConfig>(`${SERVER_API_BASE}/api/v1/energy/workshop-configs/${id}`, data)
}

export async function deleteWorkshopConfig(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/workshop-configs/${id}`)
}

export async function fetchWorkshopPersonnelCandidates(): Promise<EnergyPersonnelCandidate[]> {
  return apiGet<EnergyPersonnelCandidate[]>(
    `${SERVER_API_BASE}/api/v1/energy/workshop-configs/personnel-candidates`
  )
}

export async function fetchAvailableRules(): Promise<AlertRuleCandidate[]> {
  return apiGet<AlertRuleCandidate[]>(
    `${SERVER_API_BASE}/api/v1/energy/workshop-configs/available-rules`
  )
}

export async function fetchWorkshopOptions(energyType?: string): Promise<WorkshopOption[]> {
  const searchParams = new URLSearchParams()
  if (energyType) searchParams.set('energy_type', energyType)
  const qs = searchParams.toString()
  return apiGet<WorkshopOption[]>(
    `${SERVER_API_BASE}/api/v1/energy/workshop-configs/workshop-options${qs ? `?${qs}` : ''}`
  )
}

export async function fetchWorkshopOptionsClient(energyType?: string): Promise<WorkshopOption[]> {
  const searchParams = new URLSearchParams()
  if (energyType) searchParams.set('energy_type', energyType)
  const qs = searchParams.toString()
  return apiGet<WorkshopOption[]>(
    `${CLIENT_API_BASE}/api/v1/energy/workshop-configs/workshop-options${qs ? `?${qs}` : ''}`
  )
}


// ── 能源总耗推送配置（Server Actions）──

export async function fetchDailyPushConfigs(
  page = 1,
  pageSize = 20,
  isEnabled?: boolean,
): Promise<PaginatedResponse<DailyPushConfig>> {
  const searchParams = new URLSearchParams()
  searchParams.set('page', String(page))
  searchParams.set('page_size', String(pageSize))
  if (isEnabled !== undefined) searchParams.set('is_enabled', String(isEnabled))
  return apiFetchPaginated<DailyPushConfig>(
    `${SERVER_API_BASE}/api/v1/energy/daily-report/configs?${searchParams.toString()}`
  )
}

export async function fetchDailyPushConfigById(id: string): Promise<DailyPushConfig> {
  return apiGet<DailyPushConfig>(`${SERVER_API_BASE}/api/v1/energy/daily-report/configs/${id}`)
}

export async function createDailyPushConfig(
  data: CreateDailyPushConfigInput
): Promise<DailyPushConfig> {
  return apiPost<DailyPushConfig>(`${SERVER_API_BASE}/api/v1/energy/daily-report/configs`, data)
}

export async function updateDailyPushConfig(
  id: string,
  data: UpdateDailyPushConfigInput
): Promise<DailyPushConfig> {
  return apiPut<DailyPushConfig>(`${SERVER_API_BASE}/api/v1/energy/daily-report/configs/${id}`, data)
}

export async function deleteDailyPushConfig(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/daily-report/configs/${id}`)
}

export async function sendDailyReport(
  data: DailyReportSendRequest
): Promise<{ success: boolean; sent_to: number; total_users: number; message: string }> {
  return apiPost<{ success: boolean; sent_to: number; total_users: number; message: string }>(
    `${SERVER_API_BASE}/api/v1/energy/daily-report/send`,
    data
  )
}

export async function fetchDailyPushPersonnelCandidates(): Promise<EnergyPersonnelCandidate[]> {
  return apiGet<EnergyPersonnelCandidate[]>(
    `${SERVER_API_BASE}/api/v1/energy/daily-report/personnel-candidates`
  )
}


// ── 氮气月度推送配置 ──

export async function fetchNitrogenPushConfigs(
  page = 1,
  pageSize = 20,
  isEnabled?: boolean,
): Promise<PaginatedResponse<NitrogenPushConfig>> {
  const searchParams = new URLSearchParams()
  searchParams.set('page', String(page))
  searchParams.set('page_size', String(pageSize))
  if (isEnabled !== undefined) searchParams.set('is_enabled', String(isEnabled))
  return apiFetchPaginated<NitrogenPushConfig>(
    `${SERVER_API_BASE}/api/v1/energy/nitrogen-report/configs?${searchParams.toString()}`
  )
}

export async function fetchNitrogenPushConfigById(id: string): Promise<NitrogenPushConfig> {
  return apiGet<NitrogenPushConfig>(`${SERVER_API_BASE}/api/v1/energy/nitrogen-report/configs/${id}`)
}

export async function createNitrogenPushConfig(
  data: CreateNitrogenPushConfigInput
): Promise<NitrogenPushConfig> {
  return apiPost<NitrogenPushConfig>(`${SERVER_API_BASE}/api/v1/energy/nitrogen-report/configs`, data)
}

export async function updateNitrogenPushConfig(
  id: string,
  data: UpdateNitrogenPushConfigInput
): Promise<NitrogenPushConfig> {
  return apiPut<NitrogenPushConfig>(`${SERVER_API_BASE}/api/v1/energy/nitrogen-report/configs/${id}`, data)
}

export async function deleteNitrogenPushConfig(id: string): Promise<void> {
  await apiDelete(`${SERVER_API_BASE}/api/v1/energy/nitrogen-report/configs/${id}`)
}

export async function sendNitrogenReport(
  data: NitrogenReportSendRequest
): Promise<{ success: boolean; sent_to: number; total_users: number; message: string }> {
  return apiPost<{ success: boolean; sent_to: number; total_users: number; message: string }>(
    `${SERVER_API_BASE}/api/v1/energy/nitrogen-report/send`,
    data
  )
}

export async function fetchNitrogenPushPersonnelCandidates(): Promise<EnergyPersonnelCandidate[]> {
  return apiGet<EnergyPersonnelCandidate[]>(
    `${SERVER_API_BASE}/api/v1/energy/nitrogen-report/personnel-candidates`
  )
}

// ── 峰谷用电分布 ──

export async function fetchPriceCategoryDistribution(params: {
  start_time: string
  end_time: string
  energy_type?: string
  workshop?: string
}): Promise<{ categories: { category: string; total_value: number; unit: string; percentage: number }[]; total: number; unit: string }> {
  const searchParams = new URLSearchParams()
  searchParams.set('start_time', params.start_time)
  searchParams.set('end_time', params.end_time)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  if (params.workshop) searchParams.set('workshop', params.workshop)
  return apiGet(
    `${CLIENT_API_BASE}/api/v1/energy/overview/price-category?${searchParams.toString()}`
  )
}

// ── 峰谷时段规则 ──

export async function fetchPricePeriods(): Promise<{ id: string; category: string; start_hour: number; end_hour: number; months: number[] }[]> {
  return apiGet(`${CLIENT_API_BASE}/api/v1/energy/price-periods`)
}

export async function createPricePeriod(data: { category: string; start_hour: number; end_hour: number; months: number[] }): Promise<any> {
  return apiPost(`${CLIENT_API_BASE}/api/v1/energy/price-periods`, data)
}

export async function deletePricePeriod(id: string): Promise<void> {
  await apiDelete(`${CLIENT_API_BASE}/api/v1/energy/price-periods/${id}`)
}

export async function resetPricePeriods(): Promise<any[]> {
  return apiPost(`${CLIENT_API_BASE}/api/v1/energy/price-periods/reset`, {})
}
