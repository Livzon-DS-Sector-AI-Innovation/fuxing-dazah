// ==================== 危化品库存管理（Chemical Inventory）====================
//
// 与后端 dazah-backend/app/modules/safety/schemas/chemical_inventory.py 对齐（后端为权威源）。
// 单表固定行台账：风险标记(正常/预警) + 风险说明(预警类型多选) 由系统回填。

// ── 枚举 ──

export enum RiskFlag {
  NORMAL = 'normal',
  WARN = 'warn',
}

export enum RiskNote {
  NORMAL = 'normal',
  OVER_LIMIT = 'over_limit',
  NEAR_LIMIT = 'near_limit',
  HIGH_RATIO = 'high_ratio',
  INCOMPATIBLE_STORAGE = 'incompatible_storage',
  UNCLASSIFIED = 'unclassified',
  UNIT_ANOMALY = 'unit_anomaly',
  SPECIAL_STORAGE = 'special_storage',
}

// ── 实体（总表一行）──

export interface ChemicalInventoryRecord {
  id: string
  department: string
  storage_location?: string | null
  material_name: string
  package_spec?: string | null
  quantity?: number | null
  unit?: string | null
  total_quantity_t?: number | null
  max_limit?: number | null
  max_limit_unit?: string | null
  hazard_classes?: string[] | null
  category?: string | null
  last_updated_at?: string | null
  remark?: string | null
  risk_flag: string
  risk_note?: string[] | null
}

// ── 统计 / 扫描 ──

export interface ChemicalInventoryStats {
  total_records: number
  over_limit: number
  warn_count: number
  normal_count: number
  by_flag?: Record<string, number>
}

export interface ChemicalInventoryScanResult {
  changed: number
  warn_count: number
  normal_count: number
}

// ── 查询参数 ──

export interface ChemicalInventoryQueryParams {
  page?: number
  page_size?: number
  department?: string
  material_name?: string
}
