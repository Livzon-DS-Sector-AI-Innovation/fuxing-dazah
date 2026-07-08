'use server'

import '@/lib/http-server'
import { revalidatePath } from 'next/cache'
import {
  fetchInstruments,
  fetchInstrumentById,
  createInstrument as apiCreateInstrument,
  updateInstrument as apiUpdateInstrument,
  deleteInstrument as apiDeleteInstrument,
  fetchInstrumentDepartments,
  fetchInstrumentFilterOptions,
  fetchGasDetectors,
  fetchGasDetectorById,
  createGasDetector as apiCreateGasDetector,
  updateGasDetector as apiUpdateGasDetector,
  deleteGasDetector as apiDeleteGasDetector,
  fetchGasDetectorDepartments,
  fetchGasDetectorFilterOptions,
  fetchMeterOverview,
  fetchCalibrationAlerts,
  fetchReports,
  fetchReportsByInstrument,
  fetchReportsByGasDetector,
  uploadReport as apiUploadReport,
  deleteReport as apiDeleteReport,
  matchFiles,
  batchUploadReports as apiBatchUploadReports,
  extractDateFromReport,
  batchExtractDates as apiBatchExtractDates,
  batchCreateInstruments as apiBatchCreateInstruments,
  batchCreateGasDetectors as apiBatchCreateGasDetectors,
  fetchMeterDepartments,
  createDepartment as apiCreateDepartment,
  updateDepartment as apiUpdateDepartment,
  deleteDepartment as apiDeleteDepartment,
  fetchPersonnelCandidates,
  toggleDepartmentAutoNotify as apiToggleDepartmentAutoNotify,
  fetchMeterSettings,
  updateMeterSettings as apiUpdateMeterSettings,
} from '@/lib/api/meter'
import {
  InstrumentCreate,
  InstrumentUpdate,
  InstrumentFilter,
  GasDetectorCreate,
  GasDetectorUpdate,
  GasDetectorFilter,
  BatchCreateItem,
  GasDetectorBatchCreateItem,
  DepartmentCreate,
  DepartmentUpdate,
} from '@/types/meter'

// ═══════════════════════════════════════════
// 标准计量器具
// ═══════════════════════════════════════════

export async function getInstruments(params: InstrumentFilter = {}) {
  return fetchInstruments(params)
}

export async function getInstrumentById(id: string) {
  return fetchInstrumentById(id)
}

export async function createInstrument(data: InstrumentCreate) {
  const result = await apiCreateInstrument(data)
  revalidatePath('/meter/instruments')
  return result
}

export async function updateInstrument(id: string, data: InstrumentUpdate) {
  const result = await apiUpdateInstrument(id, data)
  revalidatePath('/meter/instruments')
  return result
}

export async function deleteInstrument(id: string) {
  await apiDeleteInstrument(id)
  revalidatePath('/meter/instruments')
}

export async function getInstrumentDepartments() {
  return fetchInstrumentDepartments()
}

// ═══════════════════════════════════════════
// 有毒有害可燃探测器
// ═══════════════════════════════════════════

export async function getGasDetectors(params: GasDetectorFilter = {}) {
  return fetchGasDetectors(params)
}

export async function getGasDetectorById(id: string) {
  return fetchGasDetectorById(id)
}

export async function createGasDetector(data: GasDetectorCreate) {
  const result = await apiCreateGasDetector(data)
  revalidatePath('/meter/gas-detectors')
  return result
}

export async function updateGasDetector(id: string, data: GasDetectorUpdate) {
  const result = await apiUpdateGasDetector(id, data)
  revalidatePath('/meter/gas-detectors')
  return result
}

export async function deleteGasDetector(id: string) {
  await apiDeleteGasDetector(id)
  revalidatePath('/meter/gas-detectors')
}

export async function getGasDetectorDepartments() {
  return fetchGasDetectorDepartments()
}

export async function getInstrumentFilterOptions() {
  return fetchInstrumentFilterOptions()
}

export async function getGasDetectorFilterOptions() {
  return fetchGasDetectorFilterOptions()
}

// ═══════════════════════════════════════════
// 检测报告
// ═══════════════════════════════════════════

export async function getReports(instrumentId?: string, gasDetectorId?: string) {
  return fetchReports(instrumentId, gasDetectorId)
}

export async function uploadReport(formData: FormData) {
  const result = await apiUploadReport(formData)
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return result
}

export async function deleteReport(id: string) {
  await apiDeleteReport(id)
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
}

export async function getReportsByInstrument(instrumentId: string) {
  return fetchReportsByInstrument(instrumentId)
}

export async function getReportsByGasDetector(detectorId: string) {
  return fetchReportsByGasDetector(detectorId)
}

export async function matchReportFiles(filenames: string[]) {
  return matchFiles(filenames)
}

export async function batchUploadReports(formData: FormData) {
  const result = await apiBatchUploadReports(formData)
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return result
}
export async function extractDate(reportId: string) {
  const res = await extractDateFromReport(reportId)
  if (!res.success && res.error) throw new Error(res.error)
  return res
}

// ═══════════════════════════════════════════
// 检定到期提醒
// ═══════════════════════════════════════════

export async function getCalibrationAlerts(daysBefore: number = 30, department?: string) {
  return fetchCalibrationAlerts(daysBefore, department)
}

// ═══════════════════════════════════════════
// 批量导出（Server Action — 自动注入 auth）
// ═══════════════════════════════════════════

export async function exportInstrumentReports(ids: string[]): Promise<{ blob: string; filename: string; count: number }> {
  const token = await import('@/lib/auth').then(m => m.getServerToken())
  const res = await fetch(`${process.env.API_BASE_URL}/api/v1/meter/instruments/export-reports`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return {
    blob: base64,
    filename: 'instruments_reports.zip',
    count: parseInt(res.headers.get('X-Report-Count') || '0'),
  }
}

export async function exportGasDetectorReports(ids: string[]): Promise<{ blob: string; filename: string; count: number }> {
  const token = await import('@/lib/auth').then(m => m.getServerToken())
  const res = await fetch(`${process.env.API_BASE_URL}/api/v1/meter/gas-detectors/export-reports`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return {
    blob: base64,
    filename: 'gas_detectors_reports.zip',
    count: parseInt(res.headers.get('X-Report-Count') || '0'),
  }
}

// ═══════════════════════════════════════════
// 导出检定到期提醒 Excel
// ═══════════════════════════════════════════

export async function exportCalibrationAlertsExcel(
  daysBefore: number = 30,
  department?: string,
  source?: string
): Promise<{ blob: string; filename: string }> {
  const token = await import('@/lib/auth').then(m => m.getServerToken())
  let url = `${process.env.API_BASE_URL}/api/v1/meter/calibration/alerts/export-excel?days_before=${daysBefore}`
  if (department) url += `&department=${encodeURIComponent(department)}`
  if (source) url += `&source=${source}`
  const res = await fetch(url, {
    headers: { 'Authorization': `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { blob: base64, filename: '检定到期提醒.xlsx' }
}

// ═══════════════════════════════════════════
// 导出 Excel（Server Action — 遵循当前筛选条件）
// ═══════════════════════════════════════════

export async function exportInstrumentsExcel(filters: InstrumentFilter = {}): Promise<{ blob: string; filename: string }> {
  const sp = new URLSearchParams()
  if (filters.department) sp.set('department', filters.department)
  if (filters.asset_number) sp.set('asset_number', filters.asset_number)
  if (filters.instrument_name) sp.set('instrument_name', filters.instrument_name)
  if (filters.model_spec) sp.set('model_spec', filters.model_spec)
  if (filters.accuracy_grade) sp.set('accuracy_grade', filters.accuracy_grade)
  if (filters.serial_number) sp.set('serial_number', filters.serial_number)
  if (filters.location) sp.set('location', filters.location)
  if (filters.manufacturer) sp.set('manufacturer', filters.manufacturer)
  if (filters.status) sp.set('status', filters.status)
  if (filters.calibration_unit) sp.set('calibration_unit', filters.calibration_unit)
  if (filters.calibration_result) sp.set('calibration_result', filters.calibration_result)
  if (filters.color_marking) sp.set('color_marking', filters.color_marking)
  if (filters.next_calibration_before) sp.set('next_calibration_before', filters.next_calibration_before)
  if (filters.next_calibration_after) sp.set('next_calibration_after', filters.next_calibration_after)
  if (filters.keyword) sp.set('keyword', filters.keyword)

  const token = await import('@/lib/auth').then(m => m.getServerToken())
  const res = await fetch(`${process.env.API_BASE_URL}/api/v1/meter/instruments/export-excel?${sp.toString()}`, {
    headers: { 'Authorization': `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { blob: base64, filename: '标准计量器具台账.xlsx' }
}

export async function exportGasDetectorsExcel(filters: GasDetectorFilter = {}): Promise<{ blob: string; filename: string }> {
  const sp = new URLSearchParams()
  if (filters.department) sp.set('department', filters.department)
  if (filters.instrument_name) sp.set('instrument_name', filters.instrument_name)
  if (filters.detection_model) sp.set('detection_model', filters.detection_model)
  if (filters.product_number) sp.set('product_number', filters.product_number)
  if (filters.installation_type) sp.set('installation_type', filters.installation_type)
  if (filters.installation_location) sp.set('installation_location', filters.installation_location)
  if (filters.medium) sp.set('medium', filters.medium)
  if (filters.calibration_result) sp.set('calibration_result', filters.calibration_result)
  if (filters.next_calibration_before) sp.set('next_calibration_before', filters.next_calibration_before)
  if (filters.next_calibration_after) sp.set('next_calibration_after', filters.next_calibration_after)
  if (filters.keyword) sp.set('keyword', filters.keyword)

  const token = await import('@/lib/auth').then(m => m.getServerToken())
  const res = await fetch(`${process.env.API_BASE_URL}/api/v1/meter/gas-detectors/export-excel?${sp.toString()}`, {
    headers: { 'Authorization': `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('导出失败')
  const arrayBuffer = await res.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')
  return { blob: base64, filename: '有毒有害可燃探测器台账.xlsx' }
}

// AI 批量提取
export async function batchExtractDates(reportIds: string[]) {
  const res = await apiBatchExtractDates(reportIds)
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return res
}


// ═══════════════════════════════════════════
// 仪表总览
// ═══════════════════════════════════════════

export async function getMeterOverview(source: 'instrument' | 'gas_detector') {
  return fetchMeterOverview(source)
}

// ── 批量新增 ──

export async function batchCreateInstruments(items: BatchCreateItem[]) {
  const result = await apiBatchCreateInstruments(items)
  revalidatePath('/meter/instruments')
  return result
}

export async function batchCreateGasDetectors(items: GasDetectorBatchCreateItem[]) {
  const result = await apiBatchCreateGasDetectors(items)
  revalidatePath('/meter/gas-detectors')
  return result
}

// ── 部门管理 ──

export async function getDepartments(source?: string) {
  return fetchMeterDepartments(source)
}

export async function createDepartment(data: DepartmentCreate) {
  const result = await apiCreateDepartment(data)
  revalidatePath('/meter/departments')
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return result
}

export async function updateDepartment(id: string, data: DepartmentUpdate) {
  const result = await apiUpdateDepartment(id, data)
  revalidatePath('/meter/departments')
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return result
}

export async function deleteDepartment(id: string) {
  await apiDeleteDepartment(id)
  revalidatePath('/meter/departments')
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
}

export async function getPersonnelCandidates() {
  return fetchPersonnelCandidates()
}

export async function toggleDepartmentAutoNotify(id: string) {
  const result = await apiToggleDepartmentAutoNotify(id)
  revalidatePath('/meter/departments')
  revalidatePath('/meter/instruments')
  revalidatePath('/meter/gas-detectors')
  return result
}


// ── 全局设置 ──

export async function getMeterSettings() {
  return fetchMeterSettings()
}

export async function updateMeterSettings(notify_time: string) {
  const result = await apiUpdateMeterSettings(notify_time)
  revalidatePath('/meter/departments')
  return result
}
