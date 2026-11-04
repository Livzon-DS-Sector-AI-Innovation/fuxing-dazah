import type {
  ChemicalChangeTrendResponse,
  ChemicalChangesResponse,
  ChemicalInventoryQueryParams,
  ChemicalInventoryRecord,
  ChemicalInventoryStats,
  ChemicalTrendResponse,
} from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 危化品库存记录（分页） */
export async function fetchChemicalInventoryRecords(
  params?: ChemicalInventoryQueryParams,
): Promise<{ items: ChemicalInventoryRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.material_name) sp.set('material_name', params.material_name)
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/chemical-inventory/records${qs ? `?${qs}` : ''}`)
}

/** 危化品库存风险统计 */
export async function fetchChemicalInventoryStats(): Promise<ChemicalInventoryStats> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/chemical-inventory/stats`)
}

/** 库存趋势（daily 快照逐日聚合，最近 N 个快照日） */
export async function fetchChemicalInventoryTrend(days = 30): Promise<ChemicalTrendResponse> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/chemical-inventory/trend?days=${days}`)
}

/** 物料异动明细（目标快照日 vs 前一快照日，部门×物料粒度） */
export async function fetchChemicalInventoryChanges(limit = 100): Promise<ChemicalChangesResponse> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/chemical-inventory/changes?limit=${limit}`)
}

/** 异动趋势（逐日急剧上升/下降条数，最近 N 个快照日） */
export async function fetchChemicalInventoryChangeTrend(days = 30): Promise<ChemicalChangeTrendResponse> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/chemical-inventory/changes/trend?days=${days}`)
}
