'use client'

import type {
  BatchDetail,
  IntermediateType,
  MaterialMovements,
  NodeExecutionListItem,
  ProcessRoute,
  Product,
  ProductionBatch,
  RouteGraph,
  TraceData,
} from '@/types/production'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

function qs(params: Record<string, string | number | undefined | null>): string {
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

export async function fetchRoutesClient(productId: string): Promise<ProcessRoute[]> {
  const s = qs({ product_id: productId, page: 1, page_size: 50 })
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
): Promise<MaterialMovements> {
  const params = new URLSearchParams()
  if (batchNo) params.set('batch_no', batchNo)
  const queryString = params.toString()
  return apiGet<MaterialMovements>(`${API_BASE}/api/v1/production/materials/${id}/movements${queryString ? `?${queryString}` : ''}`)
}

// ── 身份人员（全公司员工，供人员选择组件使用）──
// 已迁移到 @/lib/api/identity，此处保留重导出以兼容旧引用
export { type IdentityPersonnel, fetchIdentityPersonnel } from './identity'
