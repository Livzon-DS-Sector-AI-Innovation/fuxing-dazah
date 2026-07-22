import {
  EnergyDeviceConfig,
  CreateDeviceInput,
  UpdateDeviceInput,
  DeviceQueryParams,
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
} from '@/types/energy'
import { apiGet, apiPost, apiPut, apiDelete, apiFetchPaginated } from '@/lib/http-client'

// Server Actions 调用后端用绝对 URL，客户端调用用相对 URL（经 Next.js rewrites 代理）
const SERVER_API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'
const CLIENT_API_BASE = ''

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

