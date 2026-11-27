'use server'

import { revalidatePath } from 'next/cache'
import type {
  DepartureExportColumnCatalog,
  DepartureExportLog,
  DepartureLedgerFilterOptions,
  DepartureLedgerFilters,
  DepartureLedgerQueryParams,
  DepartureLedgerRow,
  DepartureSavedView,
  OffboardingCase,
  OffboardingCaseDetail,
  OffboardingCaseDeliveryResponse,
  OffboardingCaseStats,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload, fetchHrText } from './_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

// ─── 离职办理（办结单）───

/** 离职办理列表（分页） */
export async function fetchOffboardingCases(params: {
  status?: string
  department?: string
  keyword?: string
  date_from?: string
  date_to?: string
  /** 仅看临期 / 超期单（审批或清退中且距离职日 ≤ 2 天） */
  overdue?: boolean
  page?: number
  page_size?: number
}) {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  })
  return fetchHrApi(`/hr/offboarding-cases?${qs.toString()}`, {
    errorMessage: '加载离职办理列表失败',
  })
}

/** 离职办理统计（看板页头） */
export async function fetchOffboardingCaseStats(): Promise<{ code: number; message: string; data: OffboardingCaseStats }> {
  return fetchHrApi('/hr/offboarding-cases/stats', { errorMessage: '加载离职办理统计失败' })
}

/** 离职办理详情（含清退明细与签字状态） */
export async function fetchOffboardingCase(id: string): Promise<{ code: number; message: string; data: OffboardingCaseDetail }> {
  return fetchHrApi(`/hr/offboarding-cases/${id}`, {
    errorMessage: '加载离职办理详情失败',
  })
}

/** 发起离职办理（按员工档案建单） */
export async function createOffboardingCase(payload: {
  employee_id: string
  offboarding_date: string
  offboarding_type?: string
  reason?: string
  application_submitted?: boolean
  health_check_required?: boolean
  remark?: string
}): Promise<{ code: number; message: string; data: OffboardingCase }> {
  const res = await fetchHrApi('/hr/offboarding-cases', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '发起离职办理失败',
  })
  revalidatePath('/hr/departure')
  return res
}

/** 编辑离职办理基本信息（仅待发起审批 / 离职审批中，且没有进行中的飞书审批） */
export async function updateOffboardingCase(id: string, payload: {
  offboarding_date?: string
  offboarding_type?: string
  reason?: string | null
  application_submitted?: boolean
  health_check_required?: boolean
  remark?: string | null
}) {
  return fetchHrApi(`/hr/offboarding-cases/${id}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '保存失败',
  })
}

/** 取消离职办理 */
export async function cancelOffboardingCase(id: string) {
  const res = await fetchHrApi(`/hr/offboarding-cases/${id}/cancel`, {
    method: 'POST',
    errorMessage: '取消失败',
  })
  revalidatePath('/hr/departure')
  return res
}

/** 发起离职审批（体检门禁 + 飞书编排，未配置降级站内）；message 里带提前天数提示 */
export async function submitOffboardingApproval(id: string): Promise<{ code: number; message: string; data: OffboardingCase }> {
  return fetchHrApi(`/hr/offboarding-cases/${id}/submit-approval`, {
    method: 'POST',
    errorMessage: '发起离职审批失败',
  })
}

/** 站内登记办结（approving / clearing 降级推进） */
export async function manualOffboardingStageDone(id: string, payload: { stage: 'approving' | 'clearing'; note?: string }) {
  return fetchHrApi(`/hr/offboarding-cases/${id}/manual-stage-done`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '登记办结失败',
  })
}

/** 保存清退明细（全量替换，保持传入顺序） */
export async function saveClearanceItems(id: string, items: Record<string, unknown>[]) {
  return fetchHrApi(`/hr/offboarding-cases/${id}/clearance-items`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ items }),
    errorMessage: '保存清退明细失败',
  })
}

/** 离岗体检登记（multipart，可带报告附件） */
export async function registerOffboardingHealthCheck(id: string, formData: FormData) {
  return fetchHrApi(`/hr/offboarding-cases/${id}/health-check`, {
    method: 'POST',
    body: formData,
    errorMessage: '体检登记失败',
  })
}

/** 下载体检报告附件 */
export async function downloadOffboardingHealthCheck(id: string, filename: string) {
  const file = await fetchHrDownload(`/hr/offboarding-cases/${id}/health-check-file`, {
    errorMessage: '下载体检报告失败',
  })
  return { base64: file.base64, filename: filename || '离岗体检报告' }
}

/** 证明预览（返回 HTML 文本，核对页用） */
export async function previewOffboardingCertificate(id: string, template: 'electronic' | 'paper'): Promise<string> {
  return fetchHrText(`/hr/offboarding-cases/${id}/certificate-preview?template=${template}`, {
    errorMessage: '预览失败',
  })
}

/** 开具证明（生成 PDF 存档 + 台账回写 + 自动发邮件）；sign_url 供 HR 人工转发 */
export async function issueOffboardingCertificate(
  id: string,
  payload: { cert_template: 'electronic' | 'paper'; mail_recipient?: string },
): Promise<{ code: number; message: string; data: OffboardingCaseDeliveryResponse }> {
  const res = await fetchHrApi(`/hr/offboarding-cases/${id}/issue-certificate`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '开具证明失败',
  })
  revalidatePath('/hr/departure')
  return res
}

/**
 * 送达阶段补发 / 取签署链接：不传邮箱和手机号时只重新签发链接（旧链接作废）。
 * 短信通道未接入，签署链接靠这里取回后人工转发给员工。
 */
export async function resendOffboardingDelivery(
  id: string,
  payload: { mail_recipient?: string; sms_phone?: string } = {},
): Promise<{ code: number; message: string; data: OffboardingCaseDeliveryResponse }> {
  return fetchHrApi(`/hr/offboarding-cases/${id}/resend-delivery`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '送达处理失败',
  })
}

/** 纸质两联版签收登记（当面签字） */
export async function paperSignOffboardingCase(id: string, payload: { signed_by: string }) {
  return fetchHrApi(`/hr/offboarding-cases/${id}/paper-sign`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '登记签收失败',
  })
}

/** 办结（档案 / 证件 / 花名册 / 入职台账 / 离职台账联动） */
export async function closeOffboardingCase(id: string, payload: { account_deactivated: boolean }) {
  const res = await fetchHrApi(`/hr/offboarding-cases/${id}/close`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '办结失败',
  })
  revalidatePath('/hr/departure')
  return res
}

/** 下载证明 PDF */
export async function downloadOffboardingCertificate(id: string, caseNo: string) {
  const { base64, filename } = await fetchHrDownload(`/hr/offboarding-cases/${id}/certificate-file`, {
    errorMessage: '下载证明失败',
  })
  return { base64, filename: filename || `解除劳动关系证明_${caseNo}.pdf` }
}

// ─── 离职台账增强（筛选 / 勾选导出 / 保存视图 / 导出留痕）───

/** 台账查询：十类筛选 + 办理流程信息；分页信息在 meta */
export async function queryDepartureLedger(params: DepartureLedgerQueryParams = {}): Promise<{
  code: number
  message: string
  data: DepartureLedgerRow[]
  meta?: { page: number; page_size: number; total: number }
}> {
  return fetchHrApi('/hr/departure-ledger/query', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(params),
    errorMessage: '加载离职台账失败',
  })
}

/** 筛选下拉选项：各部门 / 岗位 / 类型 / 学历等现有取值聚合（跟随飞书源表变化） */
export async function fetchDepartureLedgerFilterOptions(): Promise<DepartureLedgerFilterOptions> {
  const res = await fetchHrApi<{ code: number; message: string; data: DepartureLedgerFilterOptions }>(
    '/hr/departure-ledger/filter-options',
    { errorMessage: '获取筛选选项失败' },
  )
  return res.data || {}
}

/** 可导出字段清单（分组）与默认勾选 */
export async function fetchDepartureExportColumns(): Promise<DepartureExportColumnCatalog> {
  const res = await fetchHrApi<{ code: number; message: string; data: DepartureExportColumnCatalog }>(
    '/hr/departure-ledger/export-columns',
    { errorMessage: '获取导出字段失败' },
  )
  return res.data || { columns: [], default_keys: [] }
}

/** 按筛选 + 勾选字段导出 Excel（后端写导出留痕） */
export async function exportDepartureLedger(
  filters: DepartureLedgerFilters,
  columns: string[],
  sort: { sort_by?: string; sort_order?: string } = {},
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/departure-ledger/export', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ ...filters, ...sort, columns }),
    errorMessage: '导出失败',
  })
  const stamp = new Date().toISOString().slice(0, 10)
  return { base64, filename: filename || `离职台账_${stamp}.xlsx` }
}

/** 导出记录（操作人 / 时间 / 条件 / 条数） */
export async function fetchDepartureExportLogs(): Promise<DepartureExportLog[]> {
  const res = await fetchHrApi<{ code: number; message: string; data: DepartureExportLog[] }>(
    '/hr/departure-ledger/export-logs',
    { errorMessage: '获取导出记录失败' },
  )
  return res.data || []
}

/** 我的保存视图 */
export async function fetchDepartureSavedViews(): Promise<DepartureSavedView[]> {
  const res = await fetchHrApi<{ code: number; message: string; data: DepartureSavedView[] }>(
    '/hr/departure-ledger/saved-views',
    { errorMessage: '获取保存视图失败' },
  )
  return res.data || []
}

export async function saveDepartureView(payload: {
  name: string
  filters: DepartureLedgerFilters
  columns: string[]
  is_default?: boolean
}): Promise<{ code: number; message: string; data: DepartureSavedView }> {
  return fetchHrApi('/hr/departure-ledger/saved-views', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '保存视图失败',
  })
}

export async function updateDepartureView(
  id: string,
  payload: { name: string; filters: DepartureLedgerFilters; columns: string[]; is_default?: boolean },
): Promise<{ code: number; message: string; data: DepartureSavedView }> {
  return fetchHrApi(`/hr/departure-ledger/saved-views/${id}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    errorMessage: '更新视图失败',
  })
}

export async function deleteDepartureView(id: string) {
  return fetchHrApi(`/hr/departure-ledger/saved-views/${id}`, {
    method: 'DELETE',
    errorMessage: '删除视图失败',
  })
}
