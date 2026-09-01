// 仓储管理 API 请求函数
// Server Actions 用绝对 URL，客户端用相对 URL

import {
  LocationCreate,
  LocationRecord,
  LocationUpdate,
  MaterialCreate,
  MaterialFilter,
  MaterialRecord,
  MaterialUpdate,
  MovementCreate,
  MovementFilter,
  MovementRecord,
  Paginated,
  StockFilter,
  StockRecord,
  StocktakeCreate,
  StocktakeRecord,
  StocktakeUpdate,
  WarehouseOverview,
} from '@/types/warehouse'
import { apiDelete, apiGet, apiPost, apiPut, apiFetchPaginated } from '@/lib/http-client'

const SERVER_API = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
/** 浏览器端 API base：优先 NEXT_PUBLIC_API_BASE_URL（直连后端）；
 *  未配置时回退相对路径（开发走 next.config rewrites，生产需在构建时配置该变量）。 */
const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''
const BASE = '/api/v1/warehouse'

// ── 概览 ──

export async function fetchWarehouseOverview(): Promise<WarehouseOverview> {
  return apiGet<WarehouseOverview>(`${SERVER_API}${BASE}/overview`)
}

// ── 物料主数据 ──

function setMaterialParams(sp: URLSearchParams, params: MaterialFilter) {
  if (params.category) sp.set('category', params.category)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchMaterials(params: MaterialFilter = {}): Promise<Paginated<MaterialRecord>> {
  const sp = new URLSearchParams()
  setMaterialParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MaterialRecord>(`${SERVER_API}${BASE}/materials${qs ? `?${qs}` : ''}`)
}

export async function fetchMaterialsClient(
  params: MaterialFilter = {}
): Promise<Paginated<MaterialRecord>> {
  const sp = new URLSearchParams()
  setMaterialParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MaterialRecord>(`${CLIENT_API}${BASE}/materials${qs ? `?${qs}` : ''}`)
}

export async function createMaterial(data: MaterialCreate): Promise<MaterialRecord> {
  return apiPost<MaterialRecord>(`${SERVER_API}${BASE}/materials`, data)
}

export async function updateMaterial(id: string, data: MaterialUpdate): Promise<MaterialRecord> {
  return apiPut<MaterialRecord>(`${SERVER_API}${BASE}/materials/${id}`, data)
}

export async function deleteMaterial(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/materials/${id}`)
}

// ── 库位 ──

export async function fetchLocations(): Promise<LocationRecord[]> {
  return apiGet<LocationRecord[]>(`${SERVER_API}${BASE}/locations`)
}

export async function fetchLocationsClient(): Promise<LocationRecord[]> {
  return apiGet<LocationRecord[]>(`${CLIENT_API}${BASE}/locations`)
}

export async function createLocation(data: LocationCreate): Promise<LocationRecord> {
  return apiPost<LocationRecord>(`${SERVER_API}${BASE}/locations`, data)
}

export async function updateLocation(id: string, data: LocationUpdate): Promise<LocationRecord> {
  return apiPut<LocationRecord>(`${SERVER_API}${BASE}/locations/${id}`, data)
}

export async function deleteLocation(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/locations/${id}`)
}

// ── 库存 ──

function setStockParams(sp: URLSearchParams, params: StockFilter) {
  if (params.category) sp.set('category', params.category)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.location_id) sp.set('location_id', params.location_id)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchStocks(params: StockFilter = {}): Promise<Paginated<StockRecord>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<StockRecord>(`${SERVER_API}${BASE}/stocks${qs ? `?${qs}` : ''}`)
}

export async function fetchStocksClient(params: StockFilter = {}): Promise<Paginated<StockRecord>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<StockRecord>(`${CLIENT_API}${BASE}/stocks${qs ? `?${qs}` : ''}`)
}

// ── 出入库 ──

function setMovementParams(sp: URLSearchParams, params: MovementFilter) {
  if (params.direction) sp.set('direction', params.direction)
  if (params.source_type) sp.set('source_type', params.source_type)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.location_id) sp.set('location_id', params.location_id)
  if (params.occurred_from) sp.set('occurred_from', params.occurred_from)
  if (params.occurred_to) sp.set('occurred_to', params.occurred_to)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
}

export async function fetchMovements(
  params: MovementFilter = {}
): Promise<Paginated<MovementRecord>> {
  const sp = new URLSearchParams()
  setMovementParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MovementRecord>(`${SERVER_API}${BASE}/movements${qs ? `?${qs}` : ''}`)
}

export async function fetchMovementsClient(
  params: MovementFilter = {}
): Promise<Paginated<MovementRecord>> {
  const sp = new URLSearchParams()
  setMovementParams(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<MovementRecord>(`${CLIENT_API}${BASE}/movements${qs ? `?${qs}` : ''}`)
}

export async function createMovement(data: MovementCreate): Promise<MovementRecord> {
  return apiPost<MovementRecord>(`${SERVER_API}${BASE}/movements`, data)
}

export async function deleteMovement(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/movements/${id}`)
}

// ── 盘点 ──

export async function fetchStocktakes(
  params: { page?: number; page_size?: number; status?: string } = {}
): Promise<Paginated<StocktakeRecord>> {
  const sp = new URLSearchParams()
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  if (params.status) sp.set('status', params.status)
  const qs = sp.toString()
  return apiFetchPaginated<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes${qs ? `?${qs}` : ''}`)
}

export async function fetchStocktake(id: string): Promise<StocktakeRecord> {
  return apiGet<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}`)
}

export async function fetchStocktakeClient(id: string): Promise<StocktakeRecord> {
  return apiGet<StocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${id}`)
}

export async function createStocktake(data: StocktakeCreate): Promise<StocktakeRecord> {
  return apiPost<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes`, data)
}

export async function updateStocktake(
  id: string,
  data: StocktakeUpdate
): Promise<StocktakeRecord> {
  return apiPut<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}`, data)
}

export async function confirmStocktake(id: string): Promise<StocktakeRecord> {
  return apiPost<StocktakeRecord>(`${SERVER_API}${BASE}/stocktakes/${id}/confirm`)
}

export async function deleteStocktake(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/stocktakes/${id}`)
}
