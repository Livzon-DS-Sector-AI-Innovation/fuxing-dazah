'use server'

import '@/lib/http-server'  // 初始化服务端 token getter
import { revalidatePath } from 'next/cache'
import {
  fetchEnergyDevices,
  fetchEnergyDeviceById,
  createEnergyDevice as apiCreateDevice,
  updateEnergyDevice as apiUpdateDevice,
  deleteEnergyDevice as apiDeleteDevice,
  fetchEnergyData,
  fetchEnergyDataHistory,
  triggerCollect as apiTriggerCollect,
  fetchCollectLogs,
  fetchCollectSettings as apiFetchCollectSettings,
  updateCollectSettings as apiUpdateCollectSettings,
  fetchAlertRules,
  fetchAlertRuleById,
  createAlertRule as apiCreateAlertRule,
  updateAlertRule as apiUpdateAlertRule,
  deleteAlertRule as apiDeleteAlertRule,
  fetchAlertRecords,
  processAlertRecord as apiProcessAlertRecord,
  fetchTypeConfigs,
  createTypeConfig as apiCreateTypeConfig,
  updateTypeConfig as apiUpdateTypeConfig,
  deleteTypeConfig as apiDeleteTypeConfig,
  clearCollectLogs as apiClearCollectLogs,
  fetchWorkshopConfigs,
  fetchWorkshopConfigById,
  createWorkshopConfig as apiCreateWorkshopConfig,
  updateWorkshopConfig as apiUpdateWorkshopConfig,
  deleteWorkshopConfig as apiDeleteWorkshopConfig,
  fetchWorkshopPersonnelCandidates,
  fetchAvailableRules,
  fetchWorkshopOptions,
  fetchDailyPushConfigs,
  fetchDailyPushConfigById,
  createDailyPushConfig as apiCreateDailyPushConfig,
  updateDailyPushConfig as apiUpdateDailyPushConfig,
  deleteDailyPushConfig as apiDeleteDailyPushConfig,
  sendDailyReport as apiSendDailyReport,
  fetchDailyPushPersonnelCandidates,
  fetchNitrogenPushConfigs,
  fetchNitrogenPushConfigById,
  createNitrogenPushConfig as apiCreateNitrogenPushConfig,
  updateNitrogenPushConfig as apiUpdateNitrogenPushConfig,
  deleteNitrogenPushConfig as apiDeleteNitrogenPushConfig,
  sendNitrogenReport as apiSendNitrogenReport,
  fetchNitrogenPushPersonnelCandidates,
  fetchAlertProcessList,
  fillAlertReason as apiFillAlertReason,
  approveAlertRecord as apiApproveAlertRecord,
  rejectAlertRecord as apiRejectAlertRecord,
} from '@/lib/api/energy'
import {
  CreateDeviceInput,
  UpdateDeviceInput,
  DeviceQueryParams,
  DataQueryParams,
  LogQueryParams,
  CreateRuleInput,
  UpdateRuleInput,
  ProcessRecordInput,
  RuleQueryParams,
  RecordQueryParams,
  CreateTypeConfigInput,
  UpdateTypeConfigInput,
  HistoryQueryParams,
  CreateWorkshopConfigInput,
  UpdateWorkshopConfigInput,
  CreateDailyPushConfigInput,
  UpdateDailyPushConfigInput,
  DailyReportSendRequest,
  CreateNitrogenPushConfigInput,
  UpdateNitrogenPushConfigInput,
  NitrogenReportSendRequest,
  EnergyOverview,
  EnergyTypeMeta,
} from '@/types/energy'
import { apiGet, apiPut } from '@/lib/http-client'

// 数据源配置 Server Actions
export async function getEnergyDevices(params: DeviceQueryParams = {}) {
  return fetchEnergyDevices(params)
}

export async function getEnergyDeviceById(id: string) {
  return fetchEnergyDeviceById(id)
}

export async function createEnergyDevice(data: CreateDeviceInput) {
  const result = await apiCreateDevice(data)
  revalidatePath('/energy/devices')
  return result
}

export async function updateEnergyDevice(id: string, data: UpdateDeviceInput) {
  const result = await apiUpdateDevice(id, data)
  revalidatePath('/energy/devices')
  return result
}

export async function deleteEnergyDevice(id: string) {
  await apiDeleteDevice(id)
  revalidatePath('/energy/devices')
}

// 能耗数据 Server Actions
export async function getEnergyData(params: DataQueryParams = {}) {
  return fetchEnergyData(params)
}

// 采集历史 Server Actions
export async function getEnergyDataHistory(params: HistoryQueryParams = {}) {
  return fetchEnergyDataHistory(params)
}

// 数据采集 Server Actions
export async function triggerCollect(platformCode?: string) {
  const result = await apiTriggerCollect(platformCode)
  revalidatePath('/energy/collect-logs')
  return result
}

export async function getCollectLogs(params: LogQueryParams = {}) {
  return fetchCollectLogs(params)
}

// 自动采集设置 Server Actions
export async function getCollectSettings() {
  return apiFetchCollectSettings()
}

export async function updateCollectSettings(data: { auto_collect_enabled?: boolean; daily_collect_time?: string }) {
  const result = await apiUpdateCollectSettings(data)
  revalidatePath('/energy/collect-logs')
  return result
}

export async function clearCollectLogs() {
  const result = await apiClearCollectLogs()
  revalidatePath('/energy/collect-logs')
  return result
}

// 预警规则 Server Actions
export async function getAlertRules(params: RuleQueryParams = {}) {
  return fetchAlertRules(params)
}

export async function getAlertRuleById(id: string) {
  return fetchAlertRuleById(id)
}

export async function createAlertRule(data: CreateRuleInput) {
  const result = await apiCreateAlertRule(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function updateAlertRule(id: string, data: UpdateRuleInput) {
  const result = await apiUpdateAlertRule(id, data)
  revalidatePath('/energy/alerts')
  return result
}

export async function deleteAlertRule(id: string) {
  await apiDeleteAlertRule(id)
  revalidatePath('/energy/alerts')
}

// 预警记录 Server Actions
export async function getAlertRecords(params: RecordQueryParams = {}) {
  return fetchAlertRecords(params)
}

export async function processAlertRecord(id: string, data: ProcessRecordInput) {
  const result = await apiProcessAlertRecord(id, data)
  revalidatePath('/energy/alerts')
  return result
}

// ── 预警处理 Server Actions ──

export async function getAlertProcessList(params: { status?: string; page?: number; page_size?: number } = {}) {
  return fetchAlertProcessList(params)
}

export async function fillAlertReason(id: string, data: { reason: string }) {
  const result = await apiFillAlertReason(id, data)
  revalidatePath('/energy/alert-process')
  return result
}

export async function approveAlertRecord(id: string) {
  await apiApproveAlertRecord(id)
  revalidatePath('/energy/alert-process')
}

export async function rejectAlertRecord(id: string) {
  const result = await apiRejectAlertRecord(id)
  revalidatePath('/energy/alert-process')
  return result
}

// 能源类型配置 Server Actions
export async function getTypeConfigs() {
  return fetchTypeConfigs()
}

export async function createTypeConfig(data: CreateTypeConfigInput) {
  const result = await apiCreateTypeConfig(data)
  revalidatePath('/energy/type-config')
  return result
}

export async function updateTypeConfig(id: string, data: UpdateTypeConfigInput) {
  const result = await apiUpdateTypeConfig(id, data)
  revalidatePath('/energy/type-config')
  return result
}

export async function deleteTypeConfig(id: string) {
  await apiDeleteTypeConfig(id)
  revalidatePath('/energy/type-config')
}

// 车间预警配置 Server Actions
export async function getWorkshopConfigs(page = 1, pageSize = 20) {
  return fetchWorkshopConfigs(page, pageSize)
}

export async function getWorkshopConfigById(id: string) {
  return fetchWorkshopConfigById(id)
}

export async function createWorkshopConfig(data: CreateWorkshopConfigInput) {
  const result = await apiCreateWorkshopConfig(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function updateWorkshopConfig(id: string, data: UpdateWorkshopConfigInput) {
  const result = await apiUpdateWorkshopConfig(id, data)
  revalidatePath('/energy/alerts')
  return result
}

export async function deleteWorkshopConfig(id: string) {
  await apiDeleteWorkshopConfig(id)
  revalidatePath('/energy/alerts')
}

export async function getWorkshopPersonnelCandidates() {
  return fetchWorkshopPersonnelCandidates()
}

export async function getAvailableRules() {
  return fetchAvailableRules()
}

export async function getWorkshopOptions(energyType?: string) {
  return fetchWorkshopOptions(energyType)
}

// 能源总耗推送配置 Server Actions
export async function getDailyPushConfigs(page = 1, pageSize = 20, isEnabled?: boolean) {
  return fetchDailyPushConfigs(page, pageSize, isEnabled)
}

export async function getDailyPushConfigById(id: string) {
  return fetchDailyPushConfigById(id)
}

export async function createDailyPushConfig(data: CreateDailyPushConfigInput) {
  const result = await apiCreateDailyPushConfig(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function updateDailyPushConfig(id: string, data: UpdateDailyPushConfigInput) {
  const result = await apiUpdateDailyPushConfig(id, data)
  revalidatePath('/energy/alerts')
  return result
}

export async function deleteDailyPushConfig(id: string) {
  await apiDeleteDailyPushConfig(id)
  revalidatePath('/energy/alerts')
}

export async function sendDailyReport(data: DailyReportSendRequest) {
  const result = await apiSendDailyReport(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function getDailyPushPersonnelCandidates() {
  return fetchDailyPushPersonnelCandidates()
}


// 氮气月度推送配置 Server Actions
export async function getNitrogenPushConfigs(page = 1, pageSize = 20, isEnabled?: boolean) {
  return fetchNitrogenPushConfigs(page, pageSize, isEnabled)
}

export async function getNitrogenPushConfigById(id: string) {
  return fetchNitrogenPushConfigById(id)
}

export async function createNitrogenPushConfig(data: CreateNitrogenPushConfigInput) {
  const result = await apiCreateNitrogenPushConfig(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function updateNitrogenPushConfig(id: string, data: UpdateNitrogenPushConfigInput) {
  const result = await apiUpdateNitrogenPushConfig(id, data)
  revalidatePath('/energy/alerts')
  return result
}

export async function deleteNitrogenPushConfig(id: string) {
  await apiDeleteNitrogenPushConfig(id)
  revalidatePath('/energy/alerts')
}

export async function sendNitrogenReport(data: NitrogenReportSendRequest) {
  const result = await apiSendNitrogenReport(data)
  revalidatePath('/energy/alerts')
  return result
}

export async function getNitrogenPushPersonnelCandidates() {
  return fetchNitrogenPushPersonnelCandidates()
}

// ═══════════════════════════════════════════════════════════════
// 能源总览 & 公共数据（Server Action — 服务端调用，解决退出重登录后 cookie 问题）
// ═══════════════════════════════════════════════════════════════

const _ENERGY_API = `${process.env.API_BASE_URL || 'http://localhost:8000'}/api/v1/energy`

export async function getEnergyOverview(params: {
  start_time: string
  end_time: string
  energy_type?: string
  granularity?: string
}): Promise<EnergyOverview> {
  const sp = new URLSearchParams()
  sp.set('start_time', params.start_time)
  sp.set('end_time', params.end_time)
  if (params.energy_type) sp.set('energy_type', params.energy_type)
  sp.set('granularity', params.granularity || 'daily')
  const json = await apiGet<any>(`${_ENERGY_API}/overview?${sp.toString()}`)
  return (json as any).data ?? json
}

export async function getEnabledTypeConfigs(): Promise<EnergyTypeMeta[]> {
  const json = await apiGet<any>(`${_ENERGY_API}/type-configs/enabled`)
  return (json as any).data ?? (json as any)
}

export async function updateEnergyDataValue(dataId: string, value: number): Promise<void> {
  await apiPut(`${_ENERGY_API}/data/${dataId}`, { value })
}

