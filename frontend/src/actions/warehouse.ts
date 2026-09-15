'use server'

import '@/lib/http-server'
import { revalidatePath } from 'next/cache'
import {
  fetchMaterials,
  fetchLocations,
  fetchMovements,
  fetchStocks,
  fetchStocktakes,
  fetchStocktake,
  fetchWarehouseOverview,
  fetchWarehouseAiAudits,
  fetchWarehouseAiAuditDetail,
  fetchWarehouseAiAuditStats,
  fetchWarehouseAiModels,
  fetchWarehouseAiScenarios,
  fetchWarehouseBitableConnections,
  fetchWarehouseConfigAudits,
  fetchWarehouseRuntimeConfigs,
  fetchWarehouseSchedulerTasks,
  putWarehouseAiModel as apiPutWarehouseAiModel,
  putWarehouseAiScenario as apiPutWarehouseAiScenario,
  putWarehouseBitableConnection as apiPutWarehouseBitableConnection,
  putWarehouseRuntimeConfig as apiPutWarehouseRuntimeConfig,
  putWarehouseSchedulerTask as apiPutWarehouseSchedulerTask,
  refreshWarehouseBitableFields as apiRefreshWarehouseBitableFields,
  testWarehouseAiModel as apiTestWarehouseAiModel,
  testWarehouseBitableConnection as apiTestWarehouseBitableConnection,
  createMaterial as apiCreateMaterial,
  updateMaterial as apiUpdateMaterial,
  deleteMaterial as apiDeleteMaterial,
  createLocation as apiCreateLocation,
  updateLocation as apiUpdateLocation,
  deleteLocation as apiDeleteLocation,
  createMovement as apiCreateMovement,
  deleteMovement as apiDeleteMovement,
  createStocktake as apiCreateStocktake,
  updateStocktake as apiUpdateStocktake,
  confirmStocktake as apiConfirmStocktake,
  deleteStocktake as apiDeleteStocktake,
  createPlan as apiCreatePlan,
  startPlan as apiStartPlan,
  cancelPlan as apiCancelPlan,
  generatePlanMovement as apiGeneratePlanMovement,
} from '@/lib/api/warehouse'
import {
  MaterialCreate,
  MaterialFilter,
  MaterialUpdate,
  LocationCreate,
  LocationUpdate,
  MovementCreate,
  MovementFilter,
  MovementPlanCreateInput,
  StockFilter,
  StocktakeCreate,
  StocktakeUpdate,
  WarehouseAiAuditListParams,
  WarehouseAiModelUpdateInput,
  WarehouseAiScenarioUpdateInput,
  WarehouseBitableUpdateInput,
  WarehouseConfigAuditKind,
  WarehouseRuntimeValue,
  WarehouseSchedulerUpdateInput,
} from '@/types/warehouse'

// ═══════════════════════════════════════════
// 概览
// ═══════════════════════════════════════════

export async function getWarehouseOverview() {
  return fetchWarehouseOverview()
}

// ═══════════════════════════════════════════
// 物料主数据
// ═══════════════════════════════════════════

export async function getMaterials(params: MaterialFilter = {}) {
  return fetchMaterials(params)
}

export async function createMaterial(data: MaterialCreate) {
  const result = await apiCreateMaterial(data)
  revalidatePath('/warehouse/inventory')
  return result
}

export async function updateMaterial(id: string, data: MaterialUpdate) {
  const result = await apiUpdateMaterial(id, data)
  revalidatePath('/warehouse/inventory')
  return result
}

export async function deleteMaterial(id: string) {
  await apiDeleteMaterial(id)
  revalidatePath('/warehouse/inventory')
}

// ═══════════════════════════════════════════
// 库位
// ═══════════════════════════════════════════

export async function getLocations() {
  return fetchLocations()
}

export async function createLocation(data: LocationCreate) {
  const result = await apiCreateLocation(data)
  revalidatePath('/warehouse/inventory')
  return result
}

export async function updateLocation(id: string, data: LocationUpdate) {
  const result = await apiUpdateLocation(id, data)
  revalidatePath('/warehouse/inventory')
  return result
}

export async function deleteLocation(id: string) {
  await apiDeleteLocation(id)
  revalidatePath('/warehouse/inventory')
}

// ═══════════════════════════════════════════
// 库存
// ═══════════════════════════════════════════

export async function getStocks(params: StockFilter = {}) {
  return fetchStocks(params)
}

// ═══════════════════════════════════════════
// 出入库
// ═══════════════════════════════════════════

export async function getMovements(params: MovementFilter = {}) {
  return fetchMovements(params)
}

export async function createMovement(data: MovementCreate) {
  const result = await apiCreateMovement(data)
  revalidatePath('/warehouse/inout')
  revalidatePath('/warehouse/inventory')
  return result
}

export async function deleteMovement(id: string) {
  await apiDeleteMovement(id)
  revalidatePath('/warehouse/inout')
  revalidatePath('/warehouse/inventory')
}

// ═══════════════════════════════════════════
// 盘点
// ═══════════════════════════════════════════

export async function getStocktakes(params: { page?: number; page_size?: number; status?: string } = {}) {
  return fetchStocktakes(params)
}

export async function getStocktake(id: string) {
  return fetchStocktake(id)
}

export async function createStocktake(data: StocktakeCreate) {
  const result = await apiCreateStocktake(data)
  revalidatePath('/warehouse/stocktake')
  return result
}

export async function updateStocktake(id: string, data: StocktakeUpdate) {
  const result = await apiUpdateStocktake(id, data)
  revalidatePath('/warehouse/stocktake')
  return result
}

export async function confirmStocktake(id: string) {
  const result = await apiConfirmStocktake(id)
  revalidatePath('/warehouse/stocktake')
  revalidatePath('/warehouse/inventory')
  return result
}

export async function deleteStocktake(id: string) {
  await apiDeleteStocktake(id)
  revalidatePath('/warehouse/stocktake')
}

// ═══════════════════════════════════════════════════════════
// 系统配置中心（tickets 08+09）
// GET：lib api client 解包 data，失败抛 Error（message 为后端中文错误）
// 写：PUT/POST 一律经 Server Actions；成功后 revalidate 配置页
// ═══════════════════════════════════════════════════════════

// ── AI 模型配置 ──

export async function getWarehouseAiModels() {
  return fetchWarehouseAiModels()
}

export async function updateWarehouseAiModel(profile: string, data: WarehouseAiModelUpdateInput) {
  const result = await apiPutWarehouseAiModel(profile, data)
  revalidatePath('/warehouse/system')
  return result
}

export async function testWarehouseAiModel(profile: string) {
  return apiTestWarehouseAiModel(profile)
}

// ── AI 场景配置 ──

export async function getWarehouseAiScenarios() {
  return fetchWarehouseAiScenarios()
}

export async function updateWarehouseAiScenario(
  scenario: string,
  input: WarehouseAiScenarioUpdateInput,
) {
  const result = await apiPutWarehouseAiScenario(scenario, input)
  revalidatePath('/warehouse/system')
  return result
}

// ── 运行参数 ──

export async function getWarehouseRuntimeConfigs() {
  return fetchWarehouseRuntimeConfigs()
}

export async function updateWarehouseRuntimeConfig(key: string, value: WarehouseRuntimeValue) {
  const result = await apiPutWarehouseRuntimeConfig(key, value)
  revalidatePath('/warehouse/system')
  return result
}

// ── 多维表格连接 ──

export async function getWarehouseBitableConnections() {
  return fetchWarehouseBitableConnections()
}

export async function updateWarehouseBitableConnection(
  tableKey: string,
  input: WarehouseBitableUpdateInput,
) {
  const result = await apiPutWarehouseBitableConnection(tableKey, input)
  revalidatePath('/warehouse/system')
  return result
}

export async function testWarehouseBitableConnection(tableKey: string) {
  return apiTestWarehouseBitableConnection(tableKey)
}

export async function refreshWarehouseBitableFields(tableKey: string) {
  return apiRefreshWarehouseBitableFields(tableKey)
}

// ── 定时任务 / 告警目标 ──

export async function getWarehouseSchedulerTasks() {
  return fetchWarehouseSchedulerTasks()
}

export async function updateWarehouseSchedulerTask(
  jobName: string,
  input: WarehouseSchedulerUpdateInput,
) {
  const result = await apiPutWarehouseSchedulerTask(jobName, input)
  revalidatePath('/warehouse/system')
  return result
}

// ── AI 调用审计 ──

export async function getWarehouseAiAudits(params: WarehouseAiAuditListParams = {}) {
  return fetchWarehouseAiAudits(params)
}

export async function getWarehouseAiAuditStats(params: { days?: number } = {}) {
  return fetchWarehouseAiAuditStats(params)
}

export async function getWarehouseAiAuditDetail(id: string) {
  return fetchWarehouseAiAuditDetail(id)
}

/** 五类配置变更审计（ConfigAuditSection 按 kind 分发取数） */
export async function getWarehouseConfigAudits(kind: WarehouseConfigAuditKind, limit = 50) {
  return fetchWarehouseConfigAudits(kind, limit)
}

// ═══════════════════════════════════════════
// 出入库计划单（V2.0 分期A）—— 写操作一律走 Server Actions
// ═══════════════════════════════════════════

export async function createMovementPlan(input: MovementPlanCreateInput) {
  const result = await apiCreatePlan(input)
  revalidatePath('/warehouse/board')
  return result
}

export async function startMovementPlan(planId: string) {
  const result = await apiStartPlan(planId)
  revalidatePath('/warehouse/board')
  return result
}

export async function cancelMovementPlan(planId: string, reason: string) {
  const result = await apiCancelPlan(planId, reason)
  revalidatePath('/warehouse/board')
  return result
}

export async function generatePlanMovementAction(
  planId: string,
  payload: { quantity?: number; remark?: string | null } = {},
) {
  const result = await apiGeneratePlanMovement(planId, payload)
  revalidatePath('/warehouse/board')
  revalidatePath('/warehouse/inventory')
  return result
}
