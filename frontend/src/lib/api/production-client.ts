'use client'

import type {
  BatchDetail,
  ChildrenAggregateResult,
  FieldTrendPoint,
  IntermediateType,
  MaterialMovements,
  MixingContainer,
  NodeExecutionListItem,
  ProcessRoute,
  Product,
  ProductionBatch,
  RouteGraph,
  StageSummary,
  StepCycleResponse,
  TraceData,
} from '@/types/production'
import { apiDelete, apiGet, apiFetchPaginated, apiPost, apiPut } from '@/lib/http-client'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
  }
  return sp.toString()
}

export async function fetchProductsClient(keyword?: string): Promise<Product[]> {
  const s = qs({ page: 1, page_size: 100, keyword })
  return apiGet<Product[]>(`${API_BASE}/api/v1/production/products?${s}`)
}

export async function fetchIntermediateTypesClient(params: {
  keyword?: string
  page?: number
  page_size?: number
} = {}): Promise<{ items: IntermediateType[]; total: number }> {
  const s = qs({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    keyword: params.keyword ?? null,
  })
  return apiFetchPaginated<IntermediateType>(
    `${API_BASE}/api/v1/production/intermediate-types?${s}`,
  )
}

// ── 设备选项（当前用户可见范围，后端经 equipment.public_api 过滤）──
export interface EquipmentOption {
  id: string
  equipment_no: string
  name: string
}

export async function fetchEquipmentOptionsClient(params: {
  keyword?: string
  page?: number
  page_size?: number
} = {}): Promise<{ items: EquipmentOption[]; total: number }> {
  const s = qs({
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
    keyword: params.keyword ?? null,
  })
  return apiFetchPaginated<EquipmentOption>(
    `${API_BASE}/api/v1/production/equipment-options?${s}`,
  )
}

export async function fetchEquipmentBriefsClient(ids: string[]): Promise<EquipmentOption[]> {
  const sp = new URLSearchParams()
  ids.forEach(id => sp.append('ids', id))
  const s = sp.toString()
  return apiGet<EquipmentOption[]>(
    `${API_BASE}/api/v1/production/equipment-briefs${s ? `?${s}` : ''}`,
  )
}

export async function fetchRoutesClient(productId?: string, status?: string): Promise<ProcessRoute[]> {
  const params: Record<string, string | number | undefined> = { product_id: productId, page: 1, page_size: 100 }
  if (status) { params.status = status }
  const s = qs(params)
  return apiGet<ProcessRoute[]>(`${API_BASE}/api/v1/production/routes?${s}`)
}

export async function fetchRouteGraphClient(routeId: string): Promise<RouteGraph> {
  return apiGet<RouteGraph>(`${API_BASE}/api/v1/production/routes/${routeId}`)
}

export async function fetchBatchesClient(params: {
  product_id: string
  status?: string
  keyword?: string
  entry_node_filter?: string
  route_id?: string
  page?: number
  page_size?: number
  order_by?: string
  order?: 'asc' | 'desc'
}): Promise<{ items: ProductionBatch[]; total: number }> {
  const s = qs({
    product_id: params.product_id,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
    status: params.status ?? null,
    keyword: params.keyword ?? null,
    entry_node_filter: params.entry_node_filter ?? null,
    route_id: params.route_id ?? null,
    order_by: params.order_by ?? null,
    order: params.order ?? null,
  })
  return apiFetchPaginated<ProductionBatch>(`${API_BASE}/api/v1/production/batches?${s}`)
}

export async function fetchBatchDetailClient(batchId: string): Promise<BatchDetail> {
  return apiGet<BatchDetail>(`${API_BASE}/api/v1/production/batches/${batchId}`)
}

export async function fetchTraceClient(batchId: string): Promise<TraceData> {
  return apiGet<TraceData>(`${API_BASE}/api/v1/production/batches/${batchId}/trace`)
}

export async function fetchNodeExecutionsClient(
  nodeId: string,
  params: {
    status?: string
    page?: number
    page_size?: number
    order_by?: string
    order?: 'asc' | 'desc'
  } = {},
): Promise<{ items: NodeExecutionListItem[]; total: number }> {
  const s = qs({
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
    status: params.status ?? null,
    order_by: params.order_by ?? null,
    order: params.order ?? null,
  })
  return apiFetchPaginated<NodeExecutionListItem>(`${API_BASE}/api/v1/production/nodes/${nodeId}/executions?${s}`)
}

export async function fetchMaterialsClient(params: {
  keyword?: string
  page?: number
  page_size?: number
} = {}): Promise<{ items: IntermediateType[]; total: number }> {
  const s = qs({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    keyword: params.keyword ?? null,
  })
  return apiFetchPaginated<IntermediateType>(
    `${API_BASE}/api/v1/production/materials?${s}`,
  )
}

export async function fetchMaterialDetailClient(id: string): Promise<IntermediateType> {
  return apiGet<IntermediateType>(`${API_BASE}/api/v1/production/materials/${id}`)
}

export async function fetchMaterialMovementsClient(
  id: string,
  batchNo?: string,
  containerName?: string,
): Promise<MaterialMovements> {
  const params = new URLSearchParams()
  if (batchNo) params.set('batch_no', batchNo)
  if (containerName) params.set('container_name', containerName)
  const queryString = params.toString()
  return apiGet<MaterialMovements>(`${API_BASE}/api/v1/production/materials/${id}/movements${queryString ? `?${queryString}` : ''}`)
}

// ── 混装容器 ──

export async function fetchMixingContainersClient(
  intermediateTypeId?: string,
): Promise<MixingContainer[]> {
  const s = qs({ intermediate_type_id: intermediateTypeId })
  return apiGet<MixingContainer[]>(`${API_BASE}/api/v1/production/mixing-containers${s ? `?${s}` : ''}`)
}

export async function createMixingContainerClient(input: {
  name: string
  intermediate_type_id: string
  line_id: string
  remark?: string | null
}): Promise<MixingContainer> {
  return apiPost<MixingContainer>(`${API_BASE}/api/v1/production/mixing-containers`, input)
}

export async function updateMixingContainerClient(
  id: string,
  input: { name?: string; line_id?: string; remark?: string | null },
): Promise<MixingContainer> {
  return apiPut<MixingContainer>(`${API_BASE}/api/v1/production/mixing-containers/${id}`, input)
}

export async function deleteMixingContainerClient(id: string): Promise<unknown> {
  return apiDelete(`${API_BASE}/api/v1/production/mixing-containers/${id}`)
}

export async function fetchAvailableContainersClient(
  intermediateTypeId?: string,
  batchId?: string,
): Promise<MixingContainer[]> {
  const s = qs({ intermediate_type_id: intermediateTypeId, batch_id: batchId })
  return apiGet<MixingContainer[]>(`${API_BASE}/api/v1/production/intermediates/available-containers${s ? `?${s}` : ''}`)
}

// ── 计划排程视图 ──
export async function fetchScheduleViewClient(params: {
  from_time?: string
  to_time?: string
  equipment_id?: string
}): Promise<import('@/types/production').ScheduleViewItem[]> {
  const s = qs({
    from_time: params.from_time ?? null,
    to_time: params.to_time ?? null,
    equipment_id: params.equipment_id ?? null,
  })
  return apiGet(`${API_BASE}/api/v1/production/plan-items/schedule-view?${s}`)
}

export async function fetchPlanOrdersClient(params: {
  status?: string
  keyword?: string
  page?: number
  page_size?: number
} = {}): Promise<import('@/types/production').PlanOrder[]> {
  const s = qs({
    status: params.status ?? null,
    keyword: params.keyword ?? null,
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
  })
  return apiGet(`${API_BASE}/api/v1/production/plan-orders?${s}`)
}

export async function fetchPlanOrderClient(id: string): Promise<import('@/types/production').PlanOrderDetail> {
  return apiGet(`${API_BASE}/api/v1/production/plan-orders/${id}`)
}

// ── 分析 ──
export async function fetchStepCycleClient(params: {
  route_id?: string
  product_id?: string
  days?: number
} = {}): Promise<StepCycleResponse> {
  const s = qs({
    route_id: params.route_id ?? null,
    product_id: params.product_id ?? null,
    days: params.days ?? 30,
  })
  return apiGet<StepCycleResponse>(`${API_BASE}/api/v1/production/analytics/step-cycle?${s}`)
}

// ── 计算字段与工段分析 ──
export async function fetchChildrenAggregateClient(
  batchId: string,
  fieldKey: string,
  nodeCode?: string,
): Promise<ChildrenAggregateResult> {
  const s = qs({ field_key: fieldKey, node_code: nodeCode ?? null })
  return apiGet<ChildrenAggregateResult>(
    `${API_BASE}/api/v1/production/batches/${batchId}/children-aggregate?${s}`,
  )
}

export async function fetchFieldTrendClient(
  routeId: string,
  nodeCode: string,
  fieldKey: string,
): Promise<FieldTrendPoint[]> {
  const s = qs({ route_id: routeId, node_code: nodeCode, field_key: fieldKey })
  return apiGet<FieldTrendPoint[]>(`${API_BASE}/api/v1/production/analytics/field-trend?${s}`)
}

export async function fetchStageSummaryClient(params: {
  stage_name?: string
  route_id?: string
  view_all?: boolean
  start_date?: string
  end_date?: string
}): Promise<StageSummary> {
  const s = qs({
    stage_name: params.stage_name ?? null,
    route_id: params.route_id ?? null,
    view_all: params.view_all ?? false,
    start_date: params.start_date ?? null,
    end_date: params.end_date ?? null,
  })
  return apiGet<StageSummary>(`${API_BASE}/api/v1/production/analytics/stage-summary?${s}`)
}

// ── 身份人员（全公司员工，供人员选择组件使用）──
// 已迁移到 @/lib/api/identity，此处保留重导出以兼容旧引用
export { type IdentityPersonnel, fetchIdentityPersonnel } from './identity'
