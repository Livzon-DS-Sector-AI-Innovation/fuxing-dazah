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
} from '@/types/energy'

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

export async function updateCollectSettings(data: { auto_collect_enabled?: boolean; auto_collect_interval_seconds?: number }) {
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

