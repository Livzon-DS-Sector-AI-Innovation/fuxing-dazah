import {
  EnergyDeviceConfig,
  CreateDeviceInput,
  UpdateDeviceInput,
  DeviceQueryParams,
  EnergyData,
  DataQueryParams,
  EnergyOverviewData,
  StatisticsParams,
  CollectLog,
  CollectLogDetail,
  LogQueryParams,
  PaginatedResponse,
  AlertRule,
  CreateRuleInput,
  UpdateRuleInput,
  RuleQueryParams,
  AlertRecord,
  ProcessRecordInput,
  RecordQueryParams,
  CollectHistoryItem,
  CollectHistoryParams,
  TrendDataPoint,
} from '@/types/energy'
import { apiGet, apiPost, apiPut, apiDelete, apiFetchPaginated } from '@/lib/http-client'

// Server Actions 调用后端用绝对 URL，客户端调用用相对 URL（经 Next.js rewrites 代理）
const SERVER_API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'
const CLIENT_API_BASE = ''

// ── 趋势数据字段映射（后端 timestamp/energy_type/total_value → 前端 time/type/value）──
function mapTrendData(trend: any[]): TrendDataPoint[] {
  return (trend || []).map((item: any) => ({
    time: item.timestamp || item.time || '',
    type: item.energy_type || item.type || '',
    value: item.total_value ?? item.value ?? 0,
  }))
}

async function unwrapOverview(res: any): Promise<EnergyOverviewData> {
  return {
    summary: res.summary,
    trend: mapTrendData(res.trend),
    distribution: res.distribution || [],
  }
}

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

export async function fetchEnergyOverview(
  params: StatisticsParams = {}
): Promise<EnergyOverviewData> {
  const searchParams = new URLSearchParams()
  if (params.start_time) searchParams.set('start_time', params.start_time)
  if (params.end_time) searchParams.set('end_time', params.end_time)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)

  const res = await apiGet<any>(
    `${SERVER_API_BASE}/api/v1/energy/overview?${searchParams.toString()}`
  )
  return unwrapOverview(res)
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

export async function fetchEnergyOverviewClient(
  params: StatisticsParams = {}
): Promise<EnergyOverviewData> {
  const searchParams = new URLSearchParams()
  if (params.start_time) searchParams.set('start_time', params.start_time)
  if (params.end_time) searchParams.set('end_time', params.end_time)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)

  const res = await apiGet<any>(
    `${CLIENT_API_BASE}/api/v1/energy/overview?${searchParams.toString()}`
  )
  return unwrapOverview(res)
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

export async function fetchCollectHistoryClient(
  params: CollectHistoryParams
): Promise<PaginatedResponse<CollectHistoryItem>> {
  const searchParams = new URLSearchParams()
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  searchParams.set('start_date', params.start_date)
  searchParams.set('end_date', params.end_date)
  if (params.device_config_id) searchParams.set('device_config_id', params.device_config_id)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<CollectHistoryItem>(
    `${CLIENT_API_BASE}/api/v1/energy/collect/history?${searchParams.toString()}`
  )
}

export async function fetchVisualizationData(energyType?: string) {
  const searchParams = new URLSearchParams()
  if (energyType) searchParams.set('energy_type', energyType)
  return apiGet<Record<string, { fields: any[]; records: any[] }>>(
    `${CLIENT_API_BASE}/api/v1/energy/visualization/data?${searchParams.toString()}`
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

// ── 采集历史（Server Actions）──

export async function fetchCollectHistory(
  params: CollectHistoryParams
): Promise<PaginatedResponse<CollectHistoryItem>> {
  const searchParams = new URLSearchParams()
  if (params.platform_code) searchParams.set('platform_code', params.platform_code)
  if (params.energy_type) searchParams.set('energy_type', params.energy_type)
  searchParams.set('start_date', params.start_date)
  searchParams.set('end_date', params.end_date)
  if (params.device_config_id) searchParams.set('device_config_id', params.device_config_id)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.page_size) searchParams.set('page_size', String(params.page_size))

  return apiFetchPaginated<CollectHistoryItem>(
    `${SERVER_API_BASE}/api/v1/energy/collect/history?${searchParams.toString()}`
  )
}
