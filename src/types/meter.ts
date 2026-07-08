// 仪表管理 - 类型定义
// 对应后端 app/modules/meter/schemas.py

// ── 通用 ──

export interface AnomalyFlag {
  raw_value?: string
  issue: string
  severity: 'warning' | 'error'
}

export interface ReportItem {
  id: string
  file_name: string
  file_size?: number
  content_type?: string
  report_date?: string
  remark?: string
  uploaded_at?: string
  download_url?: string
}

// PaginatedResponse 在 energy.ts 中已定义，此处复用

// ── 标准计量器具 ──

export interface InstrumentRecord {
  id: string
  asset_number?: string | null
  instrument_name: string
  model_spec?: string
  measurement_range?: string
  accuracy_grade?: string
  serial_number?: string
  calibration_cycle_months?: number
  location?: string
  manufacturer?: string
  status?: string
  color_marking?: string
  calibration_date?: string
  calibration_unit?: string
  calibration_result?: string
  next_calibration_date?: string
  department?: string
  sheet_name?: string
  remark?: string | null
  anomaly_flags?: Record<string, AnomalyFlag>
  is_deleted: boolean
  created_at?: string
  updated_at?: string
  reports: ReportItem[]
  has_anomaly?: boolean
  report_count?: number
}

export interface InstrumentCreate {
  asset_number: string
  instrument_name: string
  model_spec?: string
  measurement_range?: string
  accuracy_grade?: string
  serial_number?: string
  calibration_cycle_months?: number
  location?: string
  manufacturer?: string
  status?: string
  color_marking?: string
  calibration_date?: string
  calibration_unit?: string
  calibration_result?: string
  next_calibration_date?: string
  department?: string
  remark?: string
}

export interface InstrumentUpdate {
  asset_number?: string
  instrument_name?: string
  model_spec?: string
  measurement_range?: string
  accuracy_grade?: string
  serial_number?: string
  calibration_cycle_months?: number
  location?: string
  manufacturer?: string
  status?: string
  color_marking?: string
  calibration_date?: string
  calibration_unit?: string
  calibration_result?: string
  next_calibration_date?: string
  department?: string
  remark?: string | null
}

export interface InstrumentFilter {
  department?: string
  asset_number?: string
  instrument_name?: string
  model_spec?: string
  accuracy_grade?: string
  serial_number?: string
  location?: string
  manufacturer?: string
  status?: string
  calibration_unit?: string
  calibration_result?: string
  color_marking?: string
  next_calibration_before?: string
  next_calibration_after?: string
  keyword?: string
  page?: number
  page_size?: number
}

// ── 有毒有害可燃探测器 ──

export interface GasDetectorRecord {
  id: string
  instrument_name: string
  detection_model?: string
  measurement_range?: string
  product_number?: string
  installation_type?: string
  installation_location?: string
  medium?: string
  calibration_factor?: string
  manufacturer_supplier?: string
  calibration_date?: string
  detection_unit?: string
  next_calibration_date?: string
  calibration_result?: string
  manufacturer?: string
  department?: string
  sheet_name?: string
  remark?: string | null
  anomaly_flags?: Record<string, AnomalyFlag>
  is_deleted: boolean
  created_at?: string
  updated_at?: string
  reports: ReportItem[]
  has_anomaly?: boolean
  report_count?: number
}

export interface GasDetectorCreate {
  instrument_name: string
  detection_model?: string
  measurement_range?: string
  product_number?: string
  installation_type?: string
  installation_location?: string
  medium?: string
  calibration_factor?: string
  manufacturer_supplier?: string
  calibration_date?: string
  detection_unit?: string
  next_calibration_date?: string
  calibration_result?: string
  manufacturer?: string
  department?: string
  remark?: string
}

export interface GasDetectorUpdate {
  instrument_name?: string
  detection_model?: string
  measurement_range?: string
  product_number?: string
  installation_type?: string
  installation_location?: string
  medium?: string
  calibration_factor?: string
  manufacturer_supplier?: string
  calibration_date?: string
  detection_unit?: string
  next_calibration_date?: string
  calibration_result?: string
  manufacturer?: string
  department?: string
  remark?: string | null
}

export interface GasDetectorFilter {
  department?: string
  instrument_name?: string
  detection_model?: string
  product_number?: string
  installation_type?: string
  installation_location?: string
  medium?: string
  detection_unit?: string
  calibration_result?: string
  next_calibration_before?: string
  next_calibration_after?: string
  keyword?: string
  page?: number
  page_size?: number
}

// ── 检测报告 ──

export interface ReportResponse {
  id: string
  instrument_id?: string
  gas_detector_id?: string
  file_name: string
  file_size?: number
  content_type?: string
  report_date?: string
  remark?: string
  download_url?: string
  uploaded_at?: string
}

// ── 检定到期提醒 ──

export interface CalibrationAlertItem {
  source: 'instrument' | 'gas_detector'
  id: string
  serial_number?: string
  instrument_name: string
  location?: string
  department?: string
  next_calibration_date?: string
  days_until_due?: number
}

export interface ExtractDateResponse {
  success: boolean
  calibration_date?: string
  next_calibration_date?: string
  calibration_cycle_months?: number
  error?: string
}

// ── 批量上传 + 文件匹配 ──

export interface FileMatchItem {
  filename: string
  matched_type?: 'instrument' | 'gas_detector' | null
  matched_id?: string | null
  matched_name?: string | null
  matched_department?: string | null
}

export interface BatchUploadItem {
  filename: string
  instrument_id?: string | null
  gas_detector_id?: string | null
  report_date?: string | null
}

export interface BatchUploadResult {
  success: number
  failed: number
  errors: string[]
  report_ids: string[]
}

// ── 批量 AI 日期提取 ──

export interface BatchExtractRequest {
  report_ids: string[]
}

export interface BatchExtractItem {
  report_id: string
  file_name: string
  success: boolean
  calibration_date?: string | null
  next_calibration_date?: string | null
  error?: string | null
}

export interface BatchExtractResponse {
  total: number
  success: number
  failed: number
  results: BatchExtractItem[]
}

// ── SSE 流式进度事件 ──

export interface ExtractProgressEvent {
  current: number
  total: number
  report_id: string
  file_name: string
}

export interface ExtractResultEvent {
  report_id: string
  file_name: string
  status: 'success' | 'failed'
  calibration_date?: string
  next_calibration_date?: string
  error?: string
}

export interface ExtractCompleteEvent {
  total: number
  success: number
  failed: number
  interrupted: boolean
}

// ── 筛选选项 ──

export interface InstrumentFilterOptions {
  department: string[]
  asset_number: string[]
  instrument_name: string[]
  model_spec: string[]
  accuracy_grade: string[]
  serial_number: string[]
  location: string[]
  manufacturer: string[]
  status: string[]
  calibration_unit: string[]
  calibration_result: string[]
  color_marking: string[]
}

export interface GasDetectorFilterOptions {
  department: string[]
  instrument_name: string[]
  detection_model: string[]
  product_number: string[]
  installation_type: string[]
  installation_location: string[]
  medium: string[]
  detection_unit: string[]
  calibration_result: string[]
}

// ── 仪表总览 ──

export interface MeterOverview {
  total: number
  in_use: number
  overdue: number
  stopped: number
  due_today: number
  due_7d: number
  due_30d: number
  due_90d: number
}

// ── 批量新增 ──

export interface BatchCreateItem {
  asset_number?: string | null
  instrument_name: string
  model_spec?: string | null
  measurement_range?: string | null
  accuracy_grade?: string | null
  serial_number?: string | null
  calibration_cycle_months?: number | null
  location?: string | null
  manufacturer?: string | null
  status?: string | null
  color_marking?: string | null
  calibration_date?: string | null
  calibration_unit?: string | null
  calibration_result?: string | null
  next_calibration_date?: string | null
  department: string
  remark?: string | null
}

export interface BatchCreateRowResult {
  index: number
  asset_number?: string | null
  status: 'created' | 'skipped'
  id?: string | null
  message?: string | null
}

export interface BatchCreateResult {
  total: number
  created: number
  skipped: number
  results: BatchCreateRowResult[]
}

// ── 气体探测器批量新增 ──

export interface GasDetectorBatchCreateItem {
  instrument_name: string
  detection_model?: string | null
  measurement_range?: string | null
  product_number?: string | null
  installation_type?: string | null
  installation_location?: string | null
  medium?: string | null
  calibration_factor?: string | null
  manufacturer_supplier?: string | null
  calibration_date?: string | null
  calibration_result?: string | null
  detection_unit?: string | null
  next_calibration_date?: string | null
  manufacturer?: string | null
  department: string
  remark?: string | null
}

// ── 部门管理 ──

export interface DepartmentHead {
  name: string
  feishu_open_id: string
}

export interface DepartmentItem {
  id: string
  source: 'instrument' | 'gas_detector'
  name: string
  heads: DepartmentHead[]
  auto_notify_enabled: boolean
  record_count: number
  created_at?: string
  updated_at?: string
}

export interface DepartmentCreate {
  source: 'instrument' | 'gas_detector'
  name: string
  heads?: DepartmentHead[]
}

export interface DepartmentUpdate {
  name: string
  heads?: DepartmentHead[]
  auto_notify_enabled?: boolean
}

export interface PersonnelCandidate {
  name: string
  feishu_open_id: string
  department?: string | null
}

// ── Excel 台账导入 ──

export interface LedgerImportError {
  sheet: string
  row?: number | null
  type: 'error' | 'warning'
  message: string
  missing_fields: string[]
}

export interface LedgerImportSheetDetail {
  sheet_name: string
  department?: string | null
  rows: number
}

export interface LedgerImportResult {
  deleted_count: number
  imported_count: number
  sheet_count: number
  sheet_details: LedgerImportSheetDetail[]
  warnings: LedgerImportError[]
}


// ── 全局设置 ──

export interface MeterSettings {
  notify_time: string  // "HH:MM"
}
