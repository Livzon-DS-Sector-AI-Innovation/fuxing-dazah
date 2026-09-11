// Quality 模块 TypeScript 类型

// ─── 质量标准 ───

export interface QualityStandard {
  name: string
  limit: number | null
  operator: string // "≤" | "≥"
}

// ─── 杂质峰面积 ───

export interface ImpurityPeakArea {
  name: string
  first: number
  second: number
}

// ─── 杂质计算结果 ───

export interface ImpurityResult {
  name: string
  first_percent: number
  second_percent: number
  limit: number | null
  is_pass: boolean
}

// ─── 主计算结果（万古霉素B、总杂质等）───

export interface CalculatedResult {
  name: string
  first_percent: number
  second_percent: number
  rounded_first: number
  rounded_second: number
  limit: number | null
  is_pass: boolean
}

// ─── 完整解析结果 ───

export interface LcReportData {
  product_name: string
  batch_number: string
  form_id: string
  standard_type: string

  // 供试液A 峰面积
  total_peak_area_a_first: number
  total_peak_area_a_second: number
  main_peak_area_a_first: number
  main_peak_area_a_second: number
  total_impurity_area_first: number
  total_impurity_area_second: number
  any_unknown_impurity_first: number
  any_unknown_impurity_second: number

  // 供试液B
  main_peak_area_b_first: number
  main_peak_area_b_second: number

  // 杂质峰面积
  impurity_peaks: ImpurityPeakArea[]

  // 计算结果
  vancomycin_b: CalculatedResult | null
  total_impurities: CalculatedResult | null
  impurity_results: ImpurityResult[]

  // 质量标准
  standards: QualityStandard[]

  // 汇总
  all_pass: boolean
}

// ─── 上传响应 ───

export interface UploadLcResponse {
  filename: string
  report: LcReportData
  record_id: string | null
  task_link?: {
    task_id: string
    filled: string[]
    unmatched: string[]
  } | null
  components?: {
    name: string
    first: number | null
    second: number | null
    report_value: number | null
  }[] | null
}

// ─── 检验记录列表/详情 ───

export interface InspectionRecordListItem {
  id: string
  product_name: string
  batch_number: string
  form_id: string | null
  standard_type: string | null
  all_pass: boolean
  excel_filename: string | null
  created_at: string | null
}

export interface InspectionRecordDetail extends InspectionRecordListItem {
  impurities: ImpurityResult[]
  report: LcReportData
}

// ─── 报告单记录 ───

export interface ReportRecord {
  id: string
  inspection_record_id: string
  template_path: string
  product_name: string
  batch_number: string
  file_path: string
  file_size: number | null
  created_at: string | null
}

// ─── 汇总统计 ───

export interface ProductSummary {
  product_name: string
  total: number
  pass_count: number
  fail_count: number
}

export interface HistorySummary {
  total: number
  pass_count: number
  fail_count: number
  pass_rate: number
  products: ProductSummary[]
}

// ─── 检验任务填报 ───

export type TestTaskStatus = 'in_progress' | 'pending_review' | 'completed' | 'void'

export interface TestResultItem {
  id: string
  seq: number | null
  category: string | null
  item_name: string
  sop_no: string | null
  standard_text: string | null
  operator: string | null
  limit_min: number | null
  limit_max: number | null
  method_source: string | null
  remark: string | null
  result_text: string | null
  result_value: number | null
  is_pass: boolean | null
  judge_mode: 'auto' | 'manual'
  source: 'manual' | 'parse'
  filled_at: string | null
}

export interface TestTaskListItem {
  id: string
  product_name: string
  batch_number: string
  production_date: string | null
  expiry_date: string | null
  specification: string | null
  form_id: string | null
  report_date: string | null
  status: TestTaskStatus
  created_at: string | null
  results_total: number
  results_filled: number
}

export interface TestTaskDetail {
  id: string
  product_name: string
  batch_number: string
  production_date: string | null
  expiry_date: string | null
  specification: string | null
  form_id: string | null
  report_date: string | null
  standard_document_id: string | null
  status: TestTaskStatus
  created_at: string | null
  results: TestResultItem[]
}

// ─── 按 SOP 汇总 ───

export interface SopSummaryBatch {
  task_id: string
  batch_number: string
  production_date: string | null
  expiry_date: string | null
  result_value: number | null
  result_text: string | null
  is_pass: boolean
  source: 'manual' | 'parse'
  filled_at: string | null
}

export interface SopSummaryItem {
  sop_no: string | null
  item_name: string
  category: string | null
  standard_text: string | null
  operator: string | null
  limit_min: number | null
  limit_max: number | null
  method_source: string | null
  batches: SopSummaryBatch[]
}
