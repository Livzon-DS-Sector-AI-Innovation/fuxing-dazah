// 劳保用品（labor_supply 直读域）— 目录台账 + 配备标准 + 档案应配劳保

/** 劳保用品附件元数据（检测报告/说明书） */
export interface LaborProductAttachment {
  file_token: string
  name: string
}

/** 一条劳保用品目录项（劳保用品汇总表直读视图） */
export interface LaborProduct {
  record_id: string
  name: string
  model: string
  category: string
  protection_type: string
  unit: string
  vendor: string
  lifespan_years: number | null
  report_attachments: LaborProductAttachment[]
  manual_attachments: LaborProductAttachment[]
}

/** 目录数据质量覆盖率统计 */
export interface LaborSupplyStats {
  total: number
  protection_types: Record<string, number>
  vendor_filled: number
  report_filled: number
  manual_filled: number
  lifespan_filled: number
  vendor_coverage: number
  report_coverage: number
  manual_coverage: number
  lifespan_coverage: number
}

/** GET /labor-supply/products 响应体（source 三态） */
export interface LaborSupplyProductsData {
  items: LaborProduct[]
  total: number
  stats: LaborSupplyStats
  source: 'bitable' | 'degraded' | 'not_enabled'
  meta: { page: number; page_size: number; total: number }
}

/** 档案第 7 源：一条应配劳保条目（配备标准 × 目录 join） */
export interface OhLaborPpeItem {
  name: string
  model: string
  category: string
  protection_type: string
  cycle: string
  provision: string
  monitor_item: string
  unit_workshop: string
  lifespan_years: number | null
  has_report: boolean
  source_record_id: string
}

/** 档案第 7 源信封（三级匹配链：position > dept > none） */
export interface OhLaborPpe {
  match_level: 'position' | 'dept' | 'none'
  department: string
  position: string
  items: OhLaborPpeItem[]
  match_note: string
}
