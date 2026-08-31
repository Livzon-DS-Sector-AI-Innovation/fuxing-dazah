// 仪表管理 API 请求函数
// Server Actions 用绝对 URL，客户端用相对 URL

import {
  InstrumentRecord,
  InstrumentCreate,
  InstrumentUpdate,
  InstrumentFilter,
  GasDetectorRecord,
  GasDetectorCreate,
  GasDetectorUpdate,
  GasDetectorFilter,
  ReportResponse,
  CalibrationAlertItem,
  FileMatchItem,
  BatchUploadResult,
  BatchUploadItem,
  ReportAnalyzeItem,
  ReportMatchCandidate,
  ExtractDateResponse,
  InstrumentFilterOptions,
  GasDetectorFilterOptions,
  FilterTypeaheadResult,
  MeterOverview,
  BatchCreateItem,
  BatchCreateResult,
  GasDetectorBatchCreateItem,
  BatchDeleteRequest,
  BatchDeleteResponse,
  DepartmentItem,
  DepartmentCreate,
  DepartmentUpdate,
  LedgerImportResult,
  PersonnelCandidate,
  MeterSettings,
  DateStatsResponse,
} from '@/types/meter'
import { PaginatedResponse } from '@/types/energy'
import { apiGet, apiPost, apiPut, apiDelete, apiFetchPaginated } from '@/lib/http-client'

const SERVER_API = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
/** 浏览器端 API base：优先 NEXT_PUBLIC_API_BASE_URL（直连后端）；
 *  未配置时回退相对路径（开发走 next.config rewrites，生产需在构建时配置该变量）。
 *  不再硬编码 localhost:8000 —— standalone 部署时会把请求打到每个用户的本机。 */
const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''
const BASE = '/api/v1/meter'

/** 把标准计量器具的「文本列部分匹配」参数写入 URLSearchParams。 */
export function setInstrumentLike(sp: URLSearchParams, p: InstrumentFilter) {
  const map: Record<string, string | undefined> = {
    asset_number_like: p.asset_number_like,
    instrument_name_like: p.instrument_name_like,
    model_spec_like: p.model_spec_like,
    measurement_range_like: p.measurement_range_like,
    accuracy_grade_like: p.accuracy_grade_like,
    serial_number_like: p.serial_number_like,
    location_like: p.location_like,
    manufacturer_like: p.manufacturer_like,
    calibration_unit_like: p.calibration_unit_like,
    calibration_result_like: p.calibration_result_like,
    color_marking_like: p.color_marking_like,
  }
  for (const [k, v] of Object.entries(map)) if (v) sp.set(k, v)
}

/** 把探测器的「文本列部分匹配」参数写入 URLSearchParams。 */
export function setGasDetectorLike(sp: URLSearchParams, p: GasDetectorFilter) {
  const map: Record<string, string | undefined> = {
    instrument_name_like: p.instrument_name_like,
    detection_model_like: p.detection_model_like,
    product_number_like: p.product_number_like,
    measurement_range_like: p.measurement_range_like,
    installation_type_like: p.installation_type_like,
    installation_location_like: p.installation_location_like,
    medium_like: p.medium_like,
    calibration_factor_like: p.calibration_factor_like,
    manufacturer_supplier_like: p.manufacturer_supplier_like,
    manufacturer_like: p.manufacturer_like,
    detection_unit_like: p.detection_unit_like,
    calibration_result_like: p.calibration_result_like,
  }
  for (const [k, v] of Object.entries(map)) if (v) sp.set(k, v)
}

// ═══════════════════════════════════════════
// 标准计量器具
// ═══════════════════════════════════════════

export async function fetchInstruments(
  params: InstrumentFilter = {}
): Promise<PaginatedResponse<InstrumentRecord>> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.asset_number) sp.set('asset_number', params.asset_number)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.model_spec) sp.set('model_spec', params.model_spec)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.accuracy_grade) sp.set('accuracy_grade', params.accuracy_grade)
  if (params.serial_number) sp.set('serial_number', params.serial_number)
  if (params.location) sp.set('location', params.location)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.calibration_unit) sp.set('calibration_unit', params.calibration_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.color_marking) sp.set('color_marking', params.color_marking)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.has_report !== undefined) sp.set('has_report', String(params.has_report))
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  setInstrumentLike(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<InstrumentRecord>(`${SERVER_API}${BASE}/instruments${qs ? `?${qs}` : ''}`)
}

export async function fetchInstrumentsClient(
  params: InstrumentFilter = {}
): Promise<PaginatedResponse<InstrumentRecord>> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.asset_number) sp.set('asset_number', params.asset_number)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.model_spec) sp.set('model_spec', params.model_spec)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.accuracy_grade) sp.set('accuracy_grade', params.accuracy_grade)
  if (params.serial_number) sp.set('serial_number', params.serial_number)
  if (params.location) sp.set('location', params.location)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.calibration_unit) sp.set('calibration_unit', params.calibration_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.color_marking) sp.set('color_marking', params.color_marking)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.has_report !== undefined) sp.set('has_report', String(params.has_report))
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  setInstrumentLike(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<InstrumentRecord>(`${CLIENT_API}${BASE}/instruments${qs ? `?${qs}` : ''}`)
}

export async function fetchInstrumentById(id: string): Promise<InstrumentRecord> {
  return apiGet<InstrumentRecord>(`${SERVER_API}${BASE}/instruments/${id}`)
}

export async function createInstrument(data: InstrumentCreate): Promise<InstrumentRecord> {
  return apiPost<InstrumentRecord>(`${SERVER_API}${BASE}/instruments`, data)
}

export async function updateInstrument(id: string, data: InstrumentUpdate): Promise<InstrumentRecord> {
  return apiPut<InstrumentRecord>(`${SERVER_API}${BASE}/instruments/${id}`, data)
}

export async function deleteInstrument(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/instruments/${id}`)
}

export async function batchDeleteInstruments(ids: string[]): Promise<BatchDeleteResponse> {
  return apiPost<BatchDeleteResponse>(`${SERVER_API}${BASE}/instruments/batch-delete`, { ids })
}

export async function fetchInstrumentIds(params: InstrumentFilter = {}): Promise<string[]> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.asset_number) sp.set('asset_number', params.asset_number)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.model_spec) sp.set('model_spec', params.model_spec)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.accuracy_grade) sp.set('accuracy_grade', params.accuracy_grade)
  if (params.serial_number) sp.set('serial_number', params.serial_number)
  if (params.location) sp.set('location', params.location)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.calibration_unit) sp.set('calibration_unit', params.calibration_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.color_marking) sp.set('color_marking', params.color_marking)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  setInstrumentLike(sp, params)
  return apiGet<string[]>(`${SERVER_API}${BASE}/instruments/ids?${sp.toString()}`)
}

export async function fetchInstrumentDepartments(): Promise<string[]> {
  return apiGet<string[]>(`${SERVER_API}${BASE}/departments/instruments`)
}

// ═══════════════════════════════════════════
// 有毒有害可燃探测器
// ═══════════════════════════════════════════

export async function fetchGasDetectors(
  params: GasDetectorFilter = {}
): Promise<PaginatedResponse<GasDetectorRecord>> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.detection_model) sp.set('detection_model', params.detection_model)
  if (params.product_number) sp.set('product_number', params.product_number)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.installation_type) sp.set('installation_type', params.installation_type)
  if (params.installation_location) sp.set('installation_location', params.installation_location)
  if (params.medium) sp.set('medium', params.medium)
  if (params.calibration_factor) sp.set('calibration_factor', params.calibration_factor)
  if (params.manufacturer_supplier) sp.set('manufacturer_supplier', params.manufacturer_supplier)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.detection_unit) sp.set('detection_unit', params.detection_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.has_report !== undefined) sp.set('has_report', String(params.has_report))
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  setGasDetectorLike(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<GasDetectorRecord>(`${SERVER_API}${BASE}/gas-detectors${qs ? `?${qs}` : ''}`)
}

export async function fetchGasDetectorsClient(
  params: GasDetectorFilter = {}
): Promise<PaginatedResponse<GasDetectorRecord>> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.detection_model) sp.set('detection_model', params.detection_model)
  if (params.product_number) sp.set('product_number', params.product_number)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.installation_type) sp.set('installation_type', params.installation_type)
  if (params.installation_location) sp.set('installation_location', params.installation_location)
  if (params.medium) sp.set('medium', params.medium)
  if (params.calibration_factor) sp.set('calibration_factor', params.calibration_factor)
  if (params.manufacturer_supplier) sp.set('manufacturer_supplier', params.manufacturer_supplier)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.detection_unit) sp.set('detection_unit', params.detection_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.has_report !== undefined) sp.set('has_report', String(params.has_report))
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  setGasDetectorLike(sp, params)
  const qs = sp.toString()
  return apiFetchPaginated<GasDetectorRecord>(`${CLIENT_API}${BASE}/gas-detectors${qs ? `?${qs}` : ''}`)
}

export async function fetchGasDetectorById(id: string): Promise<GasDetectorRecord> {
  return apiGet<GasDetectorRecord>(`${SERVER_API}${BASE}/gas-detectors/${id}`)
}

export async function createGasDetector(data: GasDetectorCreate): Promise<GasDetectorRecord> {
  return apiPost<GasDetectorRecord>(`${SERVER_API}${BASE}/gas-detectors`, data)
}

export async function updateGasDetector(id: string, data: GasDetectorUpdate): Promise<GasDetectorRecord> {
  return apiPut<GasDetectorRecord>(`${SERVER_API}${BASE}/gas-detectors/${id}`, data)
}

export async function deleteGasDetector(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/gas-detectors/${id}`)
}

export async function batchDeleteGasDetectors(ids: string[]): Promise<BatchDeleteResponse> {
  return apiPost<BatchDeleteResponse>(`${SERVER_API}${BASE}/gas-detectors/batch-delete`, { ids })
}

export async function fetchGasDetectorIds(params: GasDetectorFilter = {}): Promise<string[]> {
  const sp = new URLSearchParams()
  if (params.department) sp.set('department', params.department)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.detection_model) sp.set('detection_model', params.detection_model)
  if (params.product_number) sp.set('product_number', params.product_number)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.installation_type) sp.set('installation_type', params.installation_type)
  if (params.installation_location) sp.set('installation_location', params.installation_location)
  if (params.medium) sp.set('medium', params.medium)
  if (params.calibration_factor) sp.set('calibration_factor', params.calibration_factor)
  if (params.manufacturer_supplier) sp.set('manufacturer_supplier', params.manufacturer_supplier)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.detection_unit) sp.set('detection_unit', params.detection_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.next_calibration_before) sp.set('next_calibration_before', params.next_calibration_before)
  if (params.next_calibration_after) sp.set('next_calibration_after', params.next_calibration_after)
  if (params.calibration_date_before) sp.set('calibration_date_before', params.calibration_date_before)
  if (params.calibration_date_after) sp.set('calibration_date_after', params.calibration_date_after)
  if (params.keyword) sp.set('keyword', params.keyword)
  setGasDetectorLike(sp, params)
  return apiGet<string[]>(`${SERVER_API}${BASE}/gas-detectors/ids?${sp.toString()}`)
}

export async function fetchGasDetectorDepartments(): Promise<string[]> {
  return apiGet<string[]>(`${SERVER_API}${BASE}/departments/gas-detectors`)
}

// ═══════════════════════════════════════════
// 检测报告
// ═══════════════════════════════════════════

export async function fetchReports(instrumentId?: string, gasDetectorId?: string): Promise<ReportResponse[]> {
  // 报告通过仪表详情接口内嵌返回，此函数预留直接查询
  return apiGet<ReportResponse[]>(`${SERVER_API}${BASE}/reports`)
}

export async function uploadReport(formData: FormData): Promise<ReportResponse> {
  const res = await fetch(`${SERVER_API}${BASE}/reports`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`上传失败: ${res.status}`)
  const json = await res.json()
  return json.data ?? json
}

export async function deleteReport(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/reports/${id}`)
}

export function reportDownloadUrl(reportId: string): string {
  return `${SERVER_API}${BASE}/reports/${reportId}/download`
}

export function reportPreviewUrl(reportId: string): string {
  return `${SERVER_API}${BASE}/reports/${reportId}/preview`
}

export async function fetchReportsByInstrument(instrumentId: string): Promise<ReportResponse[]> {
  return apiGet<ReportResponse[]>(`${SERVER_API}${BASE}/instruments/${instrumentId}/reports`)
}

export async function fetchReportsByGasDetector(detectorId: string): Promise<ReportResponse[]> {
  return apiGet<ReportResponse[]>(`${SERVER_API}${BASE}/gas-detectors/${detectorId}/reports`)
}

/** 客户端直连批量上传：绕过 Next.js rewrite 代理和 Server Action，直连后端避免大文件代理超时。
 *  （Server Action 有 1MB body 限制，大文件批量上传只能客户端直连——规范例外，已注释说明。） */
export async function batchUploadReportsClient(formData: FormData): Promise<BatchUploadResult> {
  const res = await fetch(`${CLIENT_API}${BASE}/reports/batch`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `批量上传失败: ${res.status}` }))
    throw new Error(err.message || `批量上传失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}

/** 客户端直连报告内容识别：上传文件 → 后端提取 4 字段并匹配台账（耗时 30–120s，含 AI 视觉）。
 *  同批量上传：大文件 + 长耗时，走客户端直连。 */
export async function analyzeReportFilesClient(
  formData: FormData,
  source?: 'instrument' | 'gas_detector',
): Promise<ReportAnalyzeItem[]> {
  if (source) formData.append('source', source)
  const res = await fetch(`${CLIENT_API}${BASE}/reports/analyze`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `报告识别失败: ${res.status}` }))
    throw new Error(err.message || `报告识别失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}

/** 按名称+编号匹配台账（人工修正提取字段后重新关联）。 */
export async function matchOne(
  instrumentName?: string | null,
  serialNumber?: string | null,
  source?: 'instrument' | 'gas_detector',
): Promise<{
  matched_type: 'instrument' | 'gas_detector' | null
  matched_id: string | null
  matched_name: string | null
  matched_department: string | null
  candidates: ReportMatchCandidate[]
}> {
  const params = new URLSearchParams()
  if (instrumentName) params.set('instrument_name', instrumentName)
  if (serialNumber) params.set('serial_number', serialNumber)
  if (source) params.set('source', source)
  return apiGet(`${CLIENT_API}${BASE}/reports/match-one?${params.toString()}`)
}

export async function fetchCalibrationAlerts(daysBefore: number = 30, department?: string): Promise<CalibrationAlertItem[]> {
  let url = `${SERVER_API}${BASE}/calibration/alerts?days_before=${daysBefore}`
  if (department) url += `&department=${encodeURIComponent(department)}`
  return apiGet<CalibrationAlertItem[]>(url)
}

export async function extractDateFromReport(reportId: string): Promise<ExtractDateResponse> {
  return apiPost<ExtractDateResponse>(`${SERVER_API}${BASE}/reports/${reportId}/extract-date`)
}

// ═══════════════════════════════════════════
// 筛选选项
// ═══════════════════════════════════════════

export async function fetchInstrumentFilterOptions(): Promise<InstrumentFilterOptions> {
  return apiGet<InstrumentFilterOptions>(`${SERVER_API}${BASE}/instruments/filter-options`)
}

export async function fetchGasDetectorFilterOptions(): Promise<GasDetectorFilterOptions> {
  return apiGet<GasDetectorFilterOptions>(`${SERVER_API}${BASE}/gas-detectors/filter-options`)
}

/** 按字段 + 关键字搜索标准计量器具筛选项（typeahead）。 */
export async function fetchInstrumentTypeahead(
  field: string,
  q?: string,
  limit = 50,
): Promise<FilterTypeaheadResult> {
  const sp = new URLSearchParams({ field, limit: String(limit) })
  if (q) sp.set('q', q)
  return apiGet<FilterTypeaheadResult>(`${SERVER_API}${BASE}/instruments/filter-options/search?${sp.toString()}`)
}

/** 按字段 + 关键字搜索探测器筛选项（typeahead）。 */
export async function fetchGasDetectorTypeahead(
  field: string,
  q?: string,
  limit = 50,
): Promise<FilterTypeaheadResult> {
  const sp = new URLSearchParams({ field, limit: String(limit) })
  if (q) sp.set('q', q)
  return apiGet<FilterTypeaheadResult>(`${SERVER_API}${BASE}/gas-detectors/filter-options/search?${sp.toString()}`)
}


// ── 日期聚合统计 ──

export async function fetchInstrumentDateStats(
  field: string,
  params: InstrumentFilter = {}
): Promise<DateStatsResponse> {
  const sp = new URLSearchParams()
  sp.set('field', field)
  if (params.department) sp.set('department', params.department)
  if (params.asset_number) sp.set('asset_number', params.asset_number)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.model_spec) sp.set('model_spec', params.model_spec)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.accuracy_grade) sp.set('accuracy_grade', params.accuracy_grade)
  if (params.serial_number) sp.set('serial_number', params.serial_number)
  if (params.location) sp.set('location', params.location)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.calibration_unit) sp.set('calibration_unit', params.calibration_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.color_marking) sp.set('color_marking', params.color_marking)
  if (params.keyword) sp.set('keyword', params.keyword)
  setInstrumentLike(sp, params)
  const qs = sp.toString()
  return apiGet<DateStatsResponse>(`${SERVER_API}${BASE}/instruments/date-stats?${qs}`)
}

export async function fetchGasDetectorDateStats(
  field: string,
  params: GasDetectorFilter = {}
): Promise<DateStatsResponse> {
  const sp = new URLSearchParams()
  sp.set('field', field)
  if (params.department) sp.set('department', params.department)
  if (params.instrument_name) sp.set('instrument_name', params.instrument_name)
  if (params.detection_model) sp.set('detection_model', params.detection_model)
  if (params.product_number) sp.set('product_number', params.product_number)
  if (params.measurement_range) sp.set('measurement_range', params.measurement_range)
  if (params.installation_type) sp.set('installation_type', params.installation_type)
  if (params.installation_location) sp.set('installation_location', params.installation_location)
  if (params.medium) sp.set('medium', params.medium)
  if (params.calibration_factor) sp.set('calibration_factor', params.calibration_factor)
  if (params.manufacturer_supplier) sp.set('manufacturer_supplier', params.manufacturer_supplier)
  if (params.manufacturer) sp.set('manufacturer', params.manufacturer)
  if (params.status) sp.set('status', params.status)
  if (params.detection_unit) sp.set('detection_unit', params.detection_unit)
  if (params.calibration_result) sp.set('calibration_result', params.calibration_result)
  if (params.keyword) sp.set('keyword', params.keyword)
  setGasDetectorLike(sp, params)
  const qs = sp.toString()
  return apiGet<DateStatsResponse>(`${SERVER_API}${BASE}/gas-detectors/date-stats?${qs}`)
}


// ═══════════════════════════════════════════
// 仪表总览
// ═══════════════════════════════════════════

export async function fetchMeterOverview(source: 'instrument' | 'gas_detector'): Promise<MeterOverview> {
  return apiGet<MeterOverview>(`${SERVER_API}${BASE}/overview?source=${source}`)
}

// ── 批量新增 ──

export async function batchCreateInstruments(items: BatchCreateItem[]): Promise<BatchCreateResult> {
  return apiPost<BatchCreateResult>(`${SERVER_API}${BASE}/instruments/batch`, { items })
}

export async function batchCreateGasDetectors(
  items: GasDetectorBatchCreateItem[]
): Promise<BatchCreateResult> {
  return apiPost<BatchCreateResult>(`${SERVER_API}${BASE}/gas-detectors/batch`, { items })
}

// ── 部门管理 ──

export async function fetchMeterDepartments(source?: string): Promise<DepartmentItem[]> {
  const url = source ? `${SERVER_API}${BASE}/departments?source=${source}` : `${SERVER_API}${BASE}/departments`
  return apiGet<DepartmentItem[]>(url)
}

export async function createDepartment(data: DepartmentCreate): Promise<DepartmentItem> {
  return apiPost<DepartmentItem>(`${SERVER_API}${BASE}/departments`, data)
}

export async function updateDepartment(id: string, data: DepartmentUpdate): Promise<DepartmentItem> {
  return apiPut<DepartmentItem>(`${SERVER_API}${BASE}/departments/${id}`, data)
}

export async function deleteDepartment(id: string): Promise<void> {
  return apiDelete<void>(`${SERVER_API}${BASE}/departments/${id}`)
}

export async function fetchPersonnelCandidates(): Promise<PersonnelCandidate[]> {
  return apiGet<PersonnelCandidate[]>(`${SERVER_API}${BASE}/departments/personnel-candidates`)
}

export async function toggleDepartmentAutoNotify(id: string): Promise<DepartmentItem> {
  return apiPut<DepartmentItem>(`${SERVER_API}${BASE}/departments/${id}/auto-notify`)
}

// ── Excel 台账导入 ──

export async function importInstrumentLedger(file: File): Promise<LedgerImportResult> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${SERVER_API}${BASE}/instruments/import-ledger`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `导入失败: ${res.status}` }))
    throw new Error(err.message || `导入失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}

export async function importGasDetectorLedger(file: File): Promise<LedgerImportResult> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${SERVER_API}${BASE}/gas-detectors/import-ledger`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `导入失败: ${res.status}` }))
    throw new Error(err.message || `导入失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}


// ── 全局设置 ──

export async function fetchMeterSettings(): Promise<MeterSettings> {
  return apiGet<MeterSettings>(`${SERVER_API}${BASE}/settings`)
}

export async function updateMeterSettings(notify_time: string): Promise<MeterSettings> {
  return apiPut<MeterSettings>(`${SERVER_API}${BASE}/settings`, { notify_time })
}
