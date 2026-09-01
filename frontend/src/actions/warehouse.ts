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
} from '@/lib/api/warehouse'
import {
  MaterialCreate,
  MaterialFilter,
  MaterialUpdate,
  LocationCreate,
  LocationUpdate,
  MovementCreate,
  MovementFilter,
  StockFilter,
  StocktakeCreate,
  StocktakeUpdate,
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
