// ==================== 备件管理 ====================
export interface SparePart {
  id: string
  code: string
  name: string
  specification: string | null
  unit: string
  category: string | null
  default_supplier: string | null
  unit_price: number | null
  min_qty: number
  current_qty: number
  is_active: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
}

export interface CreateSparePartInput {
  code: string
  name: string
  specification?: string
  unit: string
  category?: string
  default_supplier?: string
  unit_price?: number
  is_active?: boolean
}

export interface UpdateSparePartInput {
  code?: string
  name?: string
  specification?: string
  unit?: string
  category?: string
  default_supplier?: string
  unit_price?: number
  is_active?: boolean
}

export interface SparePartFilters {
  category?: string
  keyword?: string
  is_active?: boolean
  page?: number
  page_size?: number
}

export interface SparePartListResponse {
  items: SparePart[]
  total: number
  page: number
  page_size: number
}

export interface StockInboundInput {
  quantity: number
  warehouse_location?: string
  remark?: string
}

export interface StockAdjustInput {
  new_qty: number
  remark?: string
}

export interface StockWarning {
  spare_part_id: string
  code: string
  name: string
  current_qty: number
  min_qty: number
}
