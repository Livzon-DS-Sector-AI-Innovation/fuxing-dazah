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
    items?: { result_id: string; item_name: string; result_value: number | null; is_pass: boolean | null }[]
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
  source: 'calc_form' | 'parse' | string
  created_at: string | null
}

export interface InspectionRecordDetail extends InspectionRecordListItem {
  impurities: ImpurityResult[]
  report: LcReportData
  raw_data?: Record<string, unknown> | null
}

// ─── 报告单记录 ───

export interface ReportRecord {
  id: string
  inspection_record_id: string | null
  test_task_id: string | null
  template_path: string
  product_name: string
  batch_number: string
  serial_no: string | null
  file_path: string
  file_size: number | null
  task_status: string | null
  audit_status: ReportAuditStatus
  audit_comment: string | null
  audited_at: string | null
  created_at: string | null
}

export type ReportAuditStatus = 'pending' | 'approved' | 'rejected'

/** 报告单审核状态展示元数据。 */
export const REPORT_AUDIT_META: Record<ReportAuditStatus, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待初审' },
  approved: { color: 'success', label: '已通过' },
  rejected: { color: 'error', label: '已退回' },
}

// ─── 汇总统计 ───

export interface ProductSummary {
  product_name: string
  total: number
  pass_count: number
  fail_count: number
  in_progress: number
}

export interface HistorySummary {
  total: number
  pass_count: number
  fail_count: number
  pass_rate: number
  in_progress: number
  products: ProductSummary[]
}

export interface SummaryMatrixRow {
  task_id: string
  product_name: string
  batch_number: string
  production_date: string | null
  report_date: string | null
  status: string
  all_pass: boolean
  cells: Record<string, { value: number | string; is_pass: boolean; unit: string }>
}

export interface SummaryMatrix {
  columns: { name: string; sop_no: string | null }[]
  rows: SummaryMatrixRow[]
}

export interface SummaryTrendPoint {
  task_id: string
  batch_number: string
  production_date: string | null
  value: number | null
  text: string | null
  is_pass: boolean
  status: string
}

export interface SummaryTrend {
  item_name: string
  unit: string
  standard_text: string | null
  operator: string | null
  limit_min: number | null
  limit_max: number | null
  points: SummaryTrendPoint[]
}

// ─── 检验任务填报 ───

export type TestTaskStatus = 'in_progress' | 'pending_review' | 'completed' | 'void'

/** 任务状态展示元数据（全模块唯一来源；此前 4 个文件各有一份副本，且 SummaryView 缺 void）。 */
export const TASK_STATUS_META: Record<TestTaskStatus, { color: string; label: string }> = {
  in_progress: { color: 'processing', label: '填报中' },
  pending_review: { color: 'warning', label: '待复核' },
  completed: { color: 'success', label: '已完成' },
  void: { color: 'default', label: '已作废' },
}

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
  pending_confirm: boolean
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

export interface TaskAttachment {
  id: string
  filename: string
  content_type: string
  size: number
  source: string
  remark: string | null
  uploaded_by: string | null
  created_at: string | null
}

export interface TaskReviewRecord {
  reviewer_id: string
  reviewer_name: string | null
  comment: string | null
  created_at: string | null
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

export interface QualityDashboard {
  today: {
    task_id: string
    product_name: string
    batch_number: string
    status: string
    filled: number
    total: number
    report_date: string | null
  }[]
  pending_review: {
    task_id: string
    product_name: string
    batch_number: string
    status: string
    filled: number
    total: number
    report_date: string | null
  }[]
  pending_review_count: number
  in_progress_count: number
  tomorrow_count: number
  recent_completed: {
    task_id: string
    product_name: string
    batch_number: string
    status: string
    filled: number
    total: number
    report_date: string | null
  }[]
}

export interface DailyReportItem {
  serial_no: string
  product_name: string
  batch_number: string
  template_path: string
  report_id: string
  audit_status: ReportAuditStatus
  created_at: string | null
}

// ─── 报告单流水月度汇总 ───

export interface MonthlyReportDay {
  date: string
  count: number
  items: DailyReportItem[]
}

export interface MonthlyReportSummary {
  month: string
  total: number
  days: MonthlyReportDay[]
}

// ─── 报告模板树（GET /api/v1/quality/templates）───

/** 模板未绑定 SOP 时，后端按号码相似度给出的匹配建议。 */
export interface TemplateMatch {
  doc_id: string
  file_no: string
  product_code: string
}

/** COA 模板 ↔ 标准文档（SOP）的绑定；未绑定为 null。 */
export interface TemplateBinding {
  sop_no: string | null
  doc_id: string | null
  description: string | null
}

/** 模板树节点：type=folder 为目录（含 name/children），type=template 为 .docx 文件（含 filename/path 等）。 */
export interface TemplateNode {
  type: 'folder' | 'template'
  /** 目录名（type=folder）。 */
  name?: string
  /** 模板文件名（type=template）。 */
  filename?: string
  /** 相对模板根目录的路径，如 妥布霉素/3205.docx（type=template）。 */
  path?: string
  /** 子节点（type=folder）。 */
  children?: TemplateNode[]
  /** 文件大小 KB（type=template）。 */
  size_kb?: number
  /** 文件修改时间（epoch 秒，type=template）。 */
  modified?: number
  /** 占位符个数（type=template）。 */
  placeholder_count?: number
  /** 已绑定的 SOP；未绑定为 null（type=template）。 */
  binding?: TemplateBinding | null
  /** 仅在未绑定时返回的匹配建议；无建议为 null。 */
  matched?: TemplateMatch | null
}


// ─── 液相计算表模板配置（表号 → 取值配置）───

export interface LcTemplateConfig {
  id: string
  table_no: string
  product_name: string
  sop_no: string | null
  description: string | null
  config: Record<string, unknown> & {
    calc?: CalcCfg
    calc_sections?: { name: string; calc: CalcCfg }[]
    merge?: { op: string; from: string[]; into: string }[]
    batch_label?: string
  }
}

export interface CalcNormalizationCfg {
  mode: 'normalization'
  rrf: number
  samples: number
  main_item: { label: string; std_name: string }
  impurities: { key: string; label: string; std_name: string }[]
  total_std_name: string
}

export interface CalcExternalStdCfg {
  mode: 'external_std'
  samples: number
  std_injections: number
  dilution_factor: number
  ppm_scale: number
  solvents: { key: string; label: string; std_name: string; limit: string | null }[]
}

export interface CalcExternalStdContentCfg {
  mode: 'external_std_content'
  samples: number
  main_std_name: string
  has_moisture?: boolean
}

export interface CalcContentMultiCfg {
  mode: 'external_std_content_multi'
  samples: number
  components: { key: string; label: string; std_name: string }[]
  total_std_name: string
}

export interface CalcImpurityVsStdCfg {
  mode: 'impurity_vs_std'
  samples: number
  components: { key: string; label: string; std_name: string }[]
  impurities: { key: string; label: string; std_name: string }[]
  total_std_name: string
}

export interface CalcImpurityStdRatioCfg {
  mode: 'impurity_std_ratio'
  samples: number
  std_vol: number
  sample_vol: number
  std_dilution: number
  sample_dilution: number
  impurities: { key: string; label: string; std_name: string }[]
  total_from: string[]
  total_std_name: string
}

export interface CalcStdCurveCfg {
  mode: 'std_curve'
  dilutions: number[]
  volume: number
  conc_factor: number
  items: { key: string; label: string; std_name: string }[]
}

export interface CalcGroupRrfCfg {
  mode: 'group_rrf'
  rrf: number
  rrf_group: string[]
  rrf_denom: string[]
  main_std_name: string
  main_total?: string | { key: string; minus: string[] }
  items: { key: string; label: string; std_name: string; sum_of?: string[] }[]
  review?: string
}

export interface CalcImpurityRrfStdCfg {
  mode: 'impurity_rrf_std'
  samples: number
  std_keys?: string[]
  rrf_from_input?: string
  items: { key: string; label: string; std_name: string; rrf?: number }[]
  review?: string
}

export type CalcCfg = CalcNormalizationCfg | CalcExternalStdCfg | CalcExternalStdContentCfg | CalcContentMultiCfg | CalcImpurityVsStdCfg | CalcImpurityStdRatioCfg | CalcStdCurveCfg | CalcGroupRrfCfg | CalcImpurityRrfStdCfg


// ─── 任务报告单 ───

export interface TaskReportItem {
  report_id: string
  serial_no: string
  template_path: string
  filename: string | null
  audit_status: ReportAuditStatus
  created_at: string | null
}


// ─── 物料容器赋码 ───

export type MaterialContainerStatus = 'labeled' | 'in_warehouse' | 'qualified' | 'issued' | 'returned' | 'void'

export const MATERIAL_CONTAINER_STATUS_META: Record<MaterialContainerStatus, { label: string; color: string }> = {
  labeled: { label: '已赋码', color: 'default' },
  in_warehouse: { label: '在库待验', color: 'gold' },
  qualified: { label: '合格', color: 'green' },
  issued: { label: '已领出', color: 'blue' },
  returned: { label: '已退库', color: 'purple' },
  void: { label: '已作废', color: 'default' },
}

export interface MaterialContainerItem {
  id: string
  container_no: string
  material_code: string
  material_name: string
  inbound_batch_no: string
  inbound_date: string | null
  location: string | null
  expiry_date: string | null
  seq: number
  status: MaterialContainerStatus
  created_at: string
}

export interface ContainerMovement {
  id: string
  container_no: string
  op_type: string
  from_status: string
  to_status: string
  related_doc: string | null
  remark: string | null
  op_at: string
}


// ─── 物料字典 / 库存概览 / 台账 ───

export interface MaterialDictItem {
  id: string
  code: string
  name: string
  category: string | null
  vendor_name: string | null
  vendor_code: string | null
  pack_spec: string | null
  min_stock: number | null
  valid_months: number | null
  remark: string | null
  created_at: string
}

export interface MaterialSummaryItem {
  material_code: string
  material_name: string
  labeled: number
  in_warehouse: number
  qualified: number
  issued: number
  returned: number
  total: number
  available: number
  near_expiry: number
  expired: number
  min_stock: number | null
  below_stock: boolean
}

export interface MaterialMovementItem {
  id: string
  container_no: string
  material_code: string | null
  material_name: string | null
  op_type: string
  from_status: string
  to_status: string
  related_doc: string | null
  remark: string | null
  op_at: string
}


// ─── 采购建议 ───

export interface PurchaseSuggestion {
  material_code: string
  material_name: string
  vendor_name: string | null
  pack_spec: string | null
  available: number
  min_stock: number
  gap: number
}


// ─── 供应商主数据 ───

export interface SupplierItem {
  id: string
  code: string
  name: string
  contact: string | null
  phone: string | null
  qual_expiry_date: string | null
  remark: string | null
  created_at: string
}


// ─── 盘点与月度报表 ───

export interface StocktakeSheet {
  id: string
  sheet_no: string
  scope_material_code: string | null
  status: string
  remark: string | null
  expected_count: number
  scanned_count: number
  missing_count: number
  extra_count: number
  anomaly_count: number
  created_at: string
}

export interface StocktakeItem {
  id: string
  container_no: string
  result: string
  status_snapshot: string | null
  material_code: string | null
  material_name: string | null
  created_at: string
}

export interface MonthlyReportItem {
  material_code: string
  material_name: string
  in_count: number
  out_count: number
  return_count: number
  status_count: number
  available: number
}


export interface SlowMovingItem {
  container_no: string
  material_code: string
  material_name: string
  inbound_batch_no: string
  inbound_date: string
  location: string | null
  age_days: number
}


// ─── 物料请验与放行 ───

export type MaterialRequestStatus = 'pending_sample' | 'sampled' | 'in_test' | 'released' | 'rejected' | 'conceded' | 'void'

export const REQUEST_STATUS_META: Record<MaterialRequestStatus, { label: string; color: string }> = {
  pending_sample: { label: '待取样', color: 'gold' },
  sampled: { label: '已取样', color: 'blue' },
  in_test: { label: '检验中', color: 'processing' },
  released: { label: '已放行', color: 'green' },
  rejected: { label: '已拒收', color: 'red' },
  conceded: { label: '让步接收', color: 'orange' },
  void: { label: '已作废', color: 'default' },
}

export interface MaterialRequestItem {
  id: string
  request_no: string
  material_code: string
  material_name: string
  vendor_code: string | null
  vendor_name: string | null
  inbound_batch_no: string
  inbound_qty: number
  inbound_date: string | null
  status: MaterialRequestStatus
  sampled_at: string | null
  sampled_qty: number | null
  verdict: string | null
  verdict_remark: string | null
  task_id: string | null
  linked_containers: number
  created_at: string
}

export interface MaterialStandardItemRow {
  id: string
  standard_id: string
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
}

export interface MaterialStandardRow {
  id: string
  material_code: string
  material_name: string
  vendor_code: string | null
  version: string | null
  remark: string | null
  created_at: string
}


// ─── 试剂/仪器台账与请检计划 ───

export type LabItemType = 'reagent' | 'reference_standard' | 'titrant' | 'instrument'

export const LAB_ITEM_TYPE_META: Record<LabItemType, string> = {
  reagent: '试剂',
  reference_standard: '对照品',
  titrant: '滴定液',
  instrument: '仪器校验',
}

export interface LabItem {
  id: string
  item_type: LabItemType
  name: string
  batch_no: string | null
  spec: string | null
  opened_at: string | null
  expiry_date: string | null
  remark: string | null
  created_at: string
}

export interface InspectionPlan {
  id: string
  department: string
  product_name: string
  batch_no: string | null
  plan_time: string
  status: 'pending' | 'inspected'
  remark: string | null
  created_at: string
}


// ─── 微生物限度/菌落计数登记 ───

export interface MicroRecord {
  id: string
  sample_name: string
  batch_number: string | null
  sample_date: string | null
  colony_count: number | null
  ai_count: number | null
  alert_limit: number | null
  action_limit: number | null
  judge: 'pass' | 'alert' | 'action' | null
  photo_keys: string[] | null
  remark: string | null
  created_at: string
}


// ─── 留样台账 ───

export interface RetainedSample {
  id: string
  source_type: 'product' | 'material'
  batch_no: string
  sample_name: string
  qty: string | null
  location: string | null
  retained_at: string | null
  destroy_due_date: string | null
  destroyed_at: string | null
  destroyed_by: string | null
  destroyed_by_name: string | null
  destroy_confirm_by: string | null
  destroy_confirm_by_name: string | null
  status: 'active' | 'destroyed'
  remark: string | null
  created_at: string
}


// ─── 环境监测 ───

export type EnvMonitorType = 'settle' | 'float' | 'particle' | 'temp_humidity' | 'pressure'

export interface EnvPoint {
  id: string
  room: string
  point_no: string
  monitor_type: EnvMonitorType
  frequency: 'per_batch' | 'weekly' | 'monthly' | null
  alert_limit: number | null
  action_limit: number | null
  status: 'active' | 'inactive'
  remark: string | null
  created_at: string
}

export interface EnvRecord {
  id: string
  point_id: string
  room: string
  point_no: string
  monitor_type: EnvMonitorType
  record_date: string
  result_value: number | null
  alert_limit: number | null
  action_limit: number | null
  judge: 'pass' | 'alert' | 'action' | null
  handle_status: 'open' | 'handled'
  handled_at: string | null
  handled_by: string | null
  handled_by_name: string | null
  handled_remark: string | null
  recorded_by: string | null
  recorded_by_name: string | null
  remark: string | null
  created_at: string
}

export interface EnvTrend {
  room: string
  point_no: string
  monitor_type: EnvMonitorType
  alert_limit: number | null
  action_limit: number | null
  items: { record_date: string; result_value: number | null; judge: 'pass' | 'alert' | 'action' | null }[]
}

export interface EnvPlan {
  id: string
  plan_date: string
  room: string
  point_no: string
  monitor_type: EnvMonitorType
  frequency: 'weekly' | 'monthly' | null
  completed: boolean
  completed_at: string | null
}

export interface ChromatogramPeak {
  name: string
  area: number | null
}

export interface BatchRelease {
  id: string
  batch_no: string
  product_name: string
  task_id: string | null
  snapshot: {
    task_status: string
    all_pass: boolean | null
    filled: number
    total: number
    reviewers: string[]
    report_serials: string[]
    retained: { qty: string | null; location: string | null; destroy_due_date: string | null; status: string } | null
  } | null
  status: 'pending' | 'released'
  released_by: string | null
  released_by_name: string | null
  released_at: string | null
  release_remark: string | null
  remark: string | null
  created_at: string
}

export interface PlanBoardItem {
  plan_id: string
  department: string
  product_name: string
  batch_no: string | null
  plan_time: string
  status: string
  notified_at: string | null
  task_id: string | null
  task_status: string | null
  sops: { sop_no: string; items: string[]; filled: number; total: number }[]
  assignments: { sop_no: string; assignee_id: string; assignee_name: string | null }[]
}

export interface TaskAssignment {
  sop_no: string
  assignee_id: string
  assignee_name: string | null
  items: string[]
  filled: number
  total: number
  remark: string | null
}

export interface BoardTask {
  task_id: string
  product_name: string
  batch_number: string
  status: string
  report_date: string | null
  filled: number
  total: number
  assignments: TaskAssignment[]
  unassigned_sops: string[]
}

export interface PersonnelItem {
  id: string
  name: string
  employee_no: string | null
  department: string | null
}

export interface QualityAlerts {
  retained: { batch_no: string; sample_name: string; location: string | null; destroy_due_date: string | null; expired: boolean }[]
  lab: { name: string; item_type: string; expiry_date: string | null; expired: boolean }[]
  env_action_open: EnvRecord[]
  env_missed: { room: string; point_no: string; monitor_type: EnvMonitorType; frequency: string; last_date: string | null }[]
  today_plans: { department: string; product_name: string; batch_no: string | null; plan_time: string }[]
}
