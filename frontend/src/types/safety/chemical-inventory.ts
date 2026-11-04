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

// ── 查询参数 ──

export interface ChemicalInventoryQueryParams {
  page?: number
  page_size?: number
  department?: string
  material_name?: string
}

// ── 趋势看板（daily 快照聚合，后端 chemical_inventory/trend.py）──

/** 逐日聚合点（现场物料总量合计 / 条目数 / 预警条目数） */
export interface ChemicalTrendPoint {
  date: string
  total_t: number | null
  item_count: number
  warn_count: number
}

export interface ChemicalTrendResponse {
  days: number
  points: ChemicalTrendPoint[]
}

/** 物料异动标记：surge=急剧上升 decline=急剧下降 new=新出现 removed=已清零 normal=小波动 */
export type ChemicalChangeFlag = 'surge' | 'decline' | 'new' | 'removed' | 'normal'

/** 部门×物料粒度的异动条目 */
export interface ChemicalChangeItem {
  department: string
  material_name: string
  prev_t: number | null
  cur_t: number | null
  delta_t: number | null
  /** 变化比例（原始倍数，0.5=50%；prev<=0 时为 null） */
  ratio: number | null
  flag: ChemicalChangeFlag
}

export interface ChemicalChangesResponse {
  target_date: string | null
  base_date: string | null
  /** D8 环比断点（前后两日快照数据源不一致），明细不可比 */
  compare_skipped: boolean
  thresholds: { ratio: number; abs_t: number } | null
  summary: {
    surge_count: number
    decline_count: number
    new_count: number
    removed_count: number
    total_materials: number
  }
  items: ChemicalChangeItem[]
}

/** 逐日急剧上升/下降条数点 */
export interface ChemicalChangeTrendPoint {
  date: string
  surge_count: number
  decline_count: number
  compare_skipped: boolean
}

export interface ChemicalChangeTrendResponse {
  days: number
  points: ChemicalChangeTrendPoint[]
}
