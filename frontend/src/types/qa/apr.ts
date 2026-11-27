// QA 年度产品审核（PQR）类型，对应后端 app/modules/qa/*_apr（/api/v1/qa/apr）。

export type AprDataKind = 'production' | 'inspection'
export type AprItemCategory = 'cpp' | 'ipc' | 'test' | 'info'
export type AprValueType = 'number' | 'text'
/** 数值列「未检出」统计口径：zero 按 0 计入统计 / exclude 不进统计。 */
export type AprNdPolicy = 'zero' | 'exclude'
export type AprReviewStatus = 'open' | 'locked'
export type AprTrendPointStatus = 'normal' | 'oot' | 'oos'

export interface AprProduct {
  id: string
  code: string
  name: string
  name_en: string | null
  is_active: boolean
  sort_order: number
  remark: string | null
  /** 列表接口额外返回：已配置的段数与列定义数（配置页展示进度用）。 */
  section_count?: number
  item_count?: number
}

export interface AprItem {
  id: string
  section_id: string
  code: string
  group_name: string | null
  category: AprItemCategory
  name_cn: string
  name_en: string | null
  value_type: AprValueType
  unit: string | null
  spec_text: string | null
  spec_min: number | null
  spec_max: number | null
  oot_min: number | null
  oot_max: number | null
  nd_policy: AprNdPolicy
  /** 数值列允许录入的文字结果（录入页快捷按钮，同时是保存白名单）。 */
  quick_values: string[]
  /** 统计数值精度（小数位）；空 = 2，汇总表尾/导出/报告格式化用。 */
  stat_precision: number | null
  trend_enabled: boolean
  required: boolean
  is_active: boolean
  sort_order: number
  remark: string | null
}

export interface AprSection {
  id: string
  product_id: string
  name: string
  data_kind: AprDataKind
  market: string | null
  stage: string | null
  multi_row: boolean
  sort_order: number
  remark: string | null
  items?: AprItem[]
}

export interface AprBatch {
  id: string
  product_id: string
  section_id: string
  year: number
  batch_no: string
  seq: number | null
  parent_batch_id: string | null
  remark: string | null
}

export interface AprTrendPoint {
  batch_id: string
  batch_no: string
  seq: number | null
  year: number
  row_seq: number
  value: number
  /** 未检出等文字结果行：value 已按口径映射（zero=0），text 是原文。 */
  nd: boolean
  text: string | null
  status: AprTrendPointStatus
}

export interface AprTrendStats {
  count: number
  /** 未检出批次数（两种口径都返回，透明口径）。 */
  nd_count?: number
  mean?: number
  stdev?: number
  plus3s?: number
  minus3s?: number
  plus4s?: number
  minus4s?: number
  max?: number
  min?: number
  /** 以下 CPK 家族与警告/行动限对齐年度回顾工具 qa_year_review；单限列只出单侧。 */
  tolerance?: number
  spec_center?: number
  ca?: number
  cp?: number
  cpku?: number
  cpkl?: number
  cpk?: number
  cpk_level?: string
  warn_max?: number
  warn_min?: number
  action_max?: number
  action_min?: number
}

export interface AprTrend {
  item: AprItem
  section: AprSection
  product: AprProduct
  year: number | null
  points: AprTrendPoint[]
  stats: AprTrendStats
}

export interface AprSummaryCell {
  num: number | null
  text: string | null
  status: AprTrendPointStatus | null
}

export interface AprSummaryRow {
  batch_id: string
  seq: number | null
  batch_no: string
  row_seq: number
  row_label: string | null
  cells: Record<string, AprSummaryCell>
}

export interface AprSummarySection {
  id: string
  name: string
  data_kind: AprDataKind
  market: string | null
  stage: string | null
  multi_row: boolean
  items: AprItem[]
  rows: AprSummaryRow[]
  column_stats: Record<string, AprTrendStats>
}

export interface AprSummary {
  product: AprProduct
  year: number
  locked: boolean
  batch_years: number[]
  sections: AprSummarySection[]
}

// ── Excel 批量导入 ──

export type AprImportMode = 'merge' | 'replace'

/** 导入错误定位：row=工作簿行号，0 表示文件级错误。 */
export interface AprImportCellError {
  row: number
  column: string | null
  message: string
}

/** 全部校验通过才写入；ok=false 时零落库。 */
export interface AprImportResult {
  ok: boolean
  mode: AprImportMode
  batches: number
  cells: number
  /** 文件中未登记、本次自动创建的批次数。 */
  registered: number
  errors: AprImportCellError[]
  total_errors: number
}

export interface AprAnnualReview {
  product_id: string
  year: number
  status: AprReviewStatus
  locked_at: string | null
  locked_by: string | null
}

// ── 请求输入 ──

export interface AprProductInput {
  code: string
  name: string
  name_en?: string | null
  is_active?: boolean
  sort_order?: number
  remark?: string | null
}

export interface AprSectionInput {
  product_id: string
  name: string
  data_kind: AprDataKind
  market?: string | null
  stage?: string | null
  multi_row?: boolean
  sort_order?: number
  remark?: string | null
}

export interface AprItemInput {
  section_id: string
  code?: string | null
  group_name?: string | null
  category?: AprItemCategory
  name_cn: string
  name_en?: string | null
  value_type?: AprValueType
  unit?: string | null
  spec_text?: string | null
  spec_min?: number | null
  spec_max?: number | null
  oot_min?: number | null
  oot_max?: number | null
  nd_policy?: AprNdPolicy
  quick_values?: string[]
  stat_precision?: number | null
  trend_enabled?: boolean
  required?: boolean
  is_active?: boolean
  sort_order?: number
  remark?: string | null
}

/** 批量建列的单行入参（所属段由接口路径给定）。 */
export type AprItemDraft = Omit<AprItemInput, 'section_id'>

export interface AprBatchInput {
  section_id: string
  year: number
  batch_no: string
  seq?: number | null
  parent_batch_id?: string | null
  remark?: string | null
}

export interface AprValueInput {
  item_id: string
  row_seq?: number
  row_label?: string | null
  value_num?: number | null
  value_text?: string | null
  remark?: string | null
}
