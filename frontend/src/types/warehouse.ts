// 仓储管理 - 类型定义
// 对应后端 app/modules/warehouse/schemas.py

import { PaginatedResponse } from '@/types/energy'

// ── 通用 ──

export type MaterialCategory = 'raw' | 'auxiliary' | 'packaging' | 'intermediate' | 'finished'
export type LocationType = 'normal' | 'cold' | 'danger'
export type MovementDirection = 'inbound' | 'outbound' | 'adjust'
export type MovementSourceType = 'purchase' | 'production' | 'sale' | 'return' | 'stocktake' | 'other'

export const MATERIAL_CATEGORY_LABEL: Record<MaterialCategory, string> = {
  raw: '原料',
  auxiliary: '辅料',
  packaging: '包材',
  intermediate: '中间体',
  finished: '成品',
}

export const LOCATION_TYPE_LABEL: Record<LocationType, string> = {
  normal: '常温',
  cold: '冷藏',
  danger: '危险品',
}

export const MOVEMENT_DIRECTION_LABEL: Record<MovementDirection, string> = {
  inbound: '入库',
  outbound: '出库',
  adjust: '盘点调整',
}

export const MOVEMENT_SOURCE_LABEL: Record<MovementSourceType, string> = {
  purchase: '采购入库',
  production: '生产领用/产出',
  sale: '销售出库',
  return: '退料',
  stocktake: '盘点调整',
  other: '其他',
}

// ── 物料主数据 ──

export interface MaterialRecord {
  id: string
  code: string
  name: string
  category: MaterialCategory
  spec?: string | null
  unit: string
  safety_stock: number
  remark?: string | null
  created_at?: string
  updated_at?: string
}

export interface MaterialCreate {
  code: string
  name: string
  category: MaterialCategory
  spec?: string | null
  unit: string
  safety_stock?: number
  remark?: string | null
}

export interface MaterialUpdate {
  name?: string
  category?: MaterialCategory
  spec?: string | null
  unit?: string
  safety_stock?: number
  remark?: string | null
}

export interface MaterialFilter {
  page?: number
  page_size?: number
  category?: MaterialCategory
  keyword?: string
}

// ── 库位 ──

export interface LocationRecord {
  id: string
  code: string
  name: string
  location_type: LocationType
  remark?: string | null
  created_at?: string
  updated_at?: string
}

export interface LocationCreate {
  code: string
  name: string
  location_type?: LocationType
  remark?: string | null
}

export interface LocationUpdate {
  name?: string
  location_type?: LocationType
  remark?: string | null
}

// ── 库存 ──

export interface StockRecord {
  id: string
  material_id: string
  material_code: string
  material_name: string
  category?: MaterialCategory | null
  unit?: string | null
  safety_stock?: number | null
  batch_no: string
  location_id: string
  location_code: string
  location_name: string
  quantity: number
}

export interface StockFilter {
  page?: number
  page_size?: number
  category?: MaterialCategory
  keyword?: string
  location_id?: string
}

// ── 出入库 ──

export interface MovementRecord {
  id: string
  movement_no: string
  direction: MovementDirection
  source_type: MovementSourceType
  material_id: string
  material_code: string
  material_name: string
  batch_no: string
  quantity: number
  unit: string
  location_id: string
  location_code: string
  location_name: string
  occurred_at: string
  remark?: string | null
  created_at?: string
}

export interface MovementCreate {
  direction: 'inbound' | 'outbound'
  source_type: Exclude<MovementSourceType, 'stocktake'>
  material_id: string
  batch_no?: string
  quantity: number
  location_id: string
  occurred_at?: string | null
  remark?: string | null
}

export interface MovementFilter {
  page?: number
  page_size?: number
  direction?: MovementDirection
  source_type?: MovementSourceType
  keyword?: string
  location_id?: string
  occurred_from?: string
  occurred_to?: string
}

// ── 盘点 ──

export interface StocktakeItemRecord {
  id: string
  material_id: string
  material_code: string
  material_name: string
  batch_no: string
  location_id: string
  location_code: string
  location_name: string
  book_quantity: number
  counted_quantity?: number | null
  remark?: string | null
  difference?: number | null
}

export interface StocktakeRecord {
  id: string
  stocktake_no: string
  status: 'draft' | 'confirmed'
  scope_location_id?: string | null
  scope_location_code?: string | null
  scope_location_name?: string | null
  remark?: string | null
  confirmed_at?: string | null
  created_at?: string
  updated_at?: string
  items: StocktakeItemRecord[]
}

export interface StocktakeCreate {
  scope_location_id?: string | null
  remark?: string | null
}

export interface StocktakeItemUpdateInput {
  item_id: string
  counted_quantity?: number | null
  remark?: string | null
}

export interface StocktakeUpdate {
  items: StocktakeItemUpdateInput[]
}

// ── 概览 ──

export interface WarehouseOverview {
  material_count: number
  location_count: number
  stock_sku_count: number
  low_stock_materials: string[]
  today_inbound_quantity: number
  today_outbound_quantity: number
}

// 分页结果沿用全局结构
export type Paginated<T> = PaginatedResponse<T>
