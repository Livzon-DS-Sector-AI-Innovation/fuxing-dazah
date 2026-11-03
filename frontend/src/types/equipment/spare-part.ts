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
  safety_qty: number
  min_order_qty: number
  warehouse_location: string | null
  is_low_stock: boolean
  reserved_qty: number
  is_active: boolean
  equipment_count: number
  department_id: string | null
  department_name: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  /** 设备可用备件出口专用：是否本设备专用件 / 单台需求数量 */
  is_linked?: boolean
  required_qty?: number
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
  department_id?: string
  initial_qty?: number
  safety_qty?: number
  min_order_qty?: number
  warehouse_location?: string
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
  department_id?: string
}

export interface StockSettingsInput {
  safety_qty?: number
  min_order_qty?: number
  warehouse_location?: string
}

export interface SparePartFilters {
  category?: string
  keyword?: string
  is_active?: boolean
  low_stock?: boolean
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

export interface StockOutboundInput {
  quantity: number
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
  specification?: string | null
  unit?: string | null
  current_qty: number
  min_qty: number
  shortage?: number
  min_order_qty?: number
  warehouse_location?: string | null
  suggested_qty?: number
}

// ==================== 备件-设备关联 ====================
export interface EquipmentSparePartLink {
  id: string
  equipment_id: string
  spare_part_id: string
  quantity: number
  spare_part_code?: string | null
  spare_part_name?: string | null
  spare_part_specification?: string | null
  spare_part_unit?: string | null
  equipment_no?: string | null
  equipment_name?: string | null
}

// ==================== 备件消耗历史 ====================
export interface OutboundTransaction {
  id: string
  spare_part_id: string
  spare_part_code: string | null
  spare_part_name: string | null
  specification: string | null
  unit: string | null
  transaction_type: string | null
  quantity: number
  work_order_id: string | null
  work_order_no: string | null
  equipment_name: string | null
  operator_name: string | null
  consumed_at: string
  remark: string | null
}

export interface EquipmentConsumptionRecord {
  id: string
  spare_part_id: string
  spare_part_code: string | null
  spare_part_name: string | null
  specification: string | null
  unit: string | null
  quantity: number
  work_order_id: string | null
  work_order_no: string | null
  consumed_at: string
  remark: string | null
}

export interface LinkEquipmentInput {
  equipment_id: string
  quantity: number
}
