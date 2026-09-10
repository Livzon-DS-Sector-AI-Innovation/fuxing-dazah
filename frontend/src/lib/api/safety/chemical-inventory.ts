import type { ChemicalInventoryRecord, ChemicalInventoryQueryParams, ChemicalInventoryStats } from '@/types/safety'
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
