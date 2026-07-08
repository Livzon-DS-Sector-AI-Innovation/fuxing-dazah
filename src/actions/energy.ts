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
  fetchEnergyOverview,
  triggerCollect as apiTriggerCollect,
  fetchCollectLogs,
  fetchAlertRules,
  fetchAlertRuleById,
  createAlertRule as apiCreateAlertRule,
  updateAlertRule as apiUpdateAlertRule,
  deleteAlertRule as apiDeleteAlertRule,
  fetchAlertRecords,
  processAlertRecord as apiProcessAlertRecord,
  fetchCollectHistory,
} from '@/lib/api/energy'
import {
  CreateDeviceInput,
  UpdateDeviceInput,
  DeviceQueryParams,
  DataQueryParams,
  StatisticsParams,
  LogQueryParams,
  CreateRuleInput,
  UpdateRuleInput,
  ProcessRecordInput,
  RuleQueryParams,
  RecordQueryParams,
  CollectHistoryParams,
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

export async function getEnergyOverview(params: StatisticsParams = {}) {
  return fetchEnergyOverview(params)
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

// 采集历史 Server Action
export async function getCollectHistory(params: CollectHistoryParams) {
  return fetchCollectHistory(params)
}
