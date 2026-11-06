'use server'

import { revalidatePath } from 'next/cache'
import { getServerToken, getImpersonateToken } from '@/lib/auth'
import type {
  UploadLcResponse,
  InspectionRecordListItem,
  InspectionRecordDetail,
  ReportRecord,
  HistorySummary,
  TestResultItem,
  TestTaskDetail,
  TestTaskListItem,
  TestTaskStatus,
  SopSummaryItem,
  TaskAttachment,
  TaskReviewRecord,
  SummaryMatrix,
  SummaryTrend,
  QualityDashboard,
  DailyReportItem,
  MonthlyReportSummary,
  TemplateNode,
  LcTemplateConfig,
  TaskReportItem,
  MaterialContainerItem,
  MaterialDictItem,
  MaterialSummaryItem,
  MaterialMovementItem,
  PurchaseSuggestion,
  SupplierItem,
  StocktakeSheet,
  LabItem,
  InspectionPlan,
  MicroRecord,
  RetainedSample,
  BatchRelease,
  BoardTask,
  PlanBoardItem,
  TaskAssignment,
  PersonnelItem,
  EnvPoint,
  EnvRecord,
  EnvTrend,
  EnvPlan,
  ChromatogramPeak,
  QualityAlerts,
  StocktakeItem,
  MonthlyReportItem,
  SlowMovingItem,
  MaterialRequestItem,
  MaterialStandardItemRow,
  MaterialStandardRow,
} from '@/types/quality'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

/** 后端错误响应体（FastAPI 的 detail / 通用 message）。 */
interface ApiErrorBody {
  detail?: string
  message?: string
}

/**
 * 上传液相计算表 Excel 并获取解析结果。
 * 使用 FormData 传输文件，不能设 Content-Type（让浏览器自动处理 boundary）。
 */
export async function uploadLcExcel(formData: FormData): Promise<UploadLcResponse> {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()

  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`

  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || err.message || '上传解析失败')
  }

  revalidatePath('/quality')
  return res.json()
}


async function _authHeaders(): Promise<Record<string, string>> {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`
  return headers
}

/** 分页查询液相解析历史记录 */
export async function fetchInspectionRecords(
  product_name?: string,
  batch_number?: string,
  page = 1,
): Promise<{ data: InspectionRecordListItem[]; meta: { total: number } }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (batch_number) qs.set('batch_number', batch_number)
  qs.set('page', String(page))
  qs.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取检验记录失败')
  return res.json()
}

/** 查询单条检验记录详情（含杂质明细） */
export async function fetchInspectionRecord(id: string): Promise<InspectionRecordDetail> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records/${id}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取检验记录详情失败')
  const body = await res.json()
  return body.data as InspectionRecordDetail
}

/** 删除检验记录（软删除） */
export async function deleteInspectionRecord(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}

/** 报告单历史列表 */
export async function fetchReportRecords(
  product_name?: string,
  batch_number?: string,
  page = 1,
  auditStatus?: string,
): Promise<{ data: ReportRecord[]; meta: { total: number } }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (batch_number) qs.set('batch_number', batch_number)
  if (auditStatus) qs.set('audit_status', auditStatus)
  qs.set('page', String(page))
  qs.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取报告单记录失败')
  return res.json()
}

/** 生成报告单（从检验记录）：返回 { filename, base64 } 供客户端下载。
 *  注意：Server Action 返回值必须可序列化，不能直接返回 Response。 */
export async function generateReport(recordId: string, template: string): Promise<{ filename: string; base64: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/generate`, {
    method: 'POST',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ inspection_record_id: recordId, template }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '生成报告单失败')
  }
  const buf = Buffer.from(await res.arrayBuffer())
  const cd = res.headers.get('content-disposition') || ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/)
  return {
    filename: m ? decodeURIComponent(m[1]) : 'coa.docx',
    base64: buf.toString('base64'),
  }
}

/** 多批次历史汇总 */
export async function fetchHistorySummary(
  product_name?: string,
  date_from?: string,
  date_to?: string,
): Promise<HistorySummary> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (date_from) qs.set('date_from', date_from)
  if (date_to) qs.set('date_to', date_to)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/history?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取汇总失败')
  const body = await res.json()
  return body.data as HistorySummary
}

/** 已检验产品列表 */
export async function fetchSummaryProducts(): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/products`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取产品列表失败')
  const body = await res.json()
  return body.data as string[]
}


// ─── 质量标准文档 / 项目行 ───

export interface StandardDocument {
  id: string
  file_no: string
  product_name: string
  product_code: string | null
  product_internal_code: string | null
  specification: string | null
  valid_years: string | null
  effective_date: string | null
  version: string | null
  template_path: string | null
  coa_binding: { template_path: string; description: string | null } | null
}

export interface StandardItem {
  id: string
  seq: number | null
  category: string | null
  item_name: string
  sop_no: string
  standard_text: string
  operator: string | null
  limit_min: number | null
  limit_max: number | null
  method_source: string | null
  remark: string | null
}

export async function fetchStandardDocuments(): Promise<{ data: StandardDocument[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取标准文档失败')
  return res.json()
}

export async function createStandardDocument(data: Partial<StandardDocument>): Promise<{ data: { id: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('创建标准文档失败')
  return res.json()
}

export async function updateStandardDocument(id: string, data: Partial<StandardDocument>): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('更新标准文档失败')
  return res.json()
}

export async function deleteStandardDocument(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除标准文档失败')
  return res.json()
}

export async function fetchStandardItems(docId: string): Promise<{ data: StandardItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${docId}/items`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取标准行失败')
  return res.json()
}

export async function createStandardItem(docId: string, data: Partial<StandardItem>): Promise<{ data: { id: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${docId}/items`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('新增标准行失败')
  return res.json()
}

export async function updateStandardItem(id: string, data: Partial<StandardItem>): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/items/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('更新标准行失败')
  return res.json()
}

export async function deleteStandardItem(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/items/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除标准行失败')
  return res.json()
}

export async function importStandardDoc(formData: FormData): Promise<{ message: string; data: { id: string; file_no: string; product_name: string; created_items: number; parsed_items: number } }> {
  const headers = await _authHeaders()
  delete headers['Content-Type']
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/import-doc`, {
    method: 'POST', headers, body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '导入失败')
  }
  return res.json()
}


// ─── 标准文档导入（预览确认流程）───

export interface StandardImportDraftItem {
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

export interface StandardImportDraft {
  document: {
    file_no: string
    product_name: string
    product_code: string | null
    product_internal_code: string | null
    specification: string | null
    valid_years: string | null
    effective_date: string | null
    version: string | null
  }
  items: StandardImportDraftItem[]
  existing: { id: string; product_name: string } | null
}

export async function importStandardDocPreview(formData: FormData): Promise<{ message: string; data: StandardImportDraft }> {
  const headers = await _authHeaders()
  delete headers['Content-Type']
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/import-doc/preview`, {
    method: 'POST', headers, body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '解析失败')
  }
  return res.json()
}

export async function importStandardDocConfirm(
  document: StandardImportDraft['document'],
  items: StandardImportDraftItem[],
): Promise<{ message: string; data: { id: string; file_no: string; created_items: number; skipped_items: number; overwritten: boolean } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/import-doc/confirm`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ document, items }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '确认导入失败')
  }
  return res.json()
}


// ─── 报告模板管理 ───

export async function fetchTemplates(): Promise<TemplateNode[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取模板列表失败')
  return res.json()
}

export async function uploadTemplate(folder: string, formData: FormData): Promise<{ filename: string; folder: string; path: string; bound: boolean; matched: { doc_id: string; file_no: string; product_code: string } | null }> {
  const headers = await _authHeaders()
  delete headers['Content-Type']
  formData.append('folder', folder)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/upload`, {
    method: 'POST', headers, body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '上传模板失败')
  }
  return res.json()
}

export async function createTemplateFolder(name: string): Promise<{ name: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/folders`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error('创建文件夹失败')
  return res.json()
}

export async function deleteTemplateFolder(name: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/folders`, {
    method: 'DELETE', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '删除文件夹失败')
  }
  return res.json()
}

export async function bindTemplate(
  template_path: string, standard_document_id: string, replaceExisting = false, description?: string,
): Promise<{ message: string; data: { template_path: string; sop_no: string | null; standard_document_id: string | null } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/bindings`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_path, standard_document_id, replace_existing: replaceExisting, description }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '绑定模板失败')
  }
  return res.json()
}

export async function unbindTemplate(template_path: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/bindings/${encodeURIComponent(template_path)}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('解绑模板失败')
  return res.json()
}

export async function deleteTemplateFile(path: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/file`, {
    method: 'DELETE', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '删除模板失败')
  }
  return res.json()
}


// ─── 检验任务填报 ───

export async function createTestTask(data: {
  product_name: string
  batch_number: string
  production_date?: string
  expiry_date?: string
  specification?: string
  form_id?: string
  report_date?: string
  culture_days?: number
  standard_document_id?: string
  standard_document_ids?: string[]
  standard_item_ids?: string[]
}): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '创建检验任务失败')
  }
  revalidatePath('/quality/task')
  return res.json()
}

export async function updateTestTaskReportDate(
  taskId: string, reportDate: string | null,
): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/report-date`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ report_date: reportDate }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新出报日期失败')
  }
  revalidatePath('/quality/task')
  return res.json()
}

export async function fetchTestTasks(
  product_name?: string, status?: TestTaskStatus, page = 1, report_date?: string, fileNo?: string,
): Promise<{ data: TestTaskListItem[]; meta: { total: number } }> {
  const params = new URLSearchParams()
  if (product_name) params.set('product_name', product_name)
  if (status) params.set('status', status)
  if (report_date) params.set('report_date', report_date)
  if (fileNo) params.set('file_no', fileNo)
  params.set('page', String(page))
  params.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks?${params.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取检验任务失败')
  return res.json()
}

export async function fetchTaskSopSummary(product_name?: string): Promise<SopSummaryItem[]> {
  const params = new URLSearchParams()
  if (product_name) params.set('product_name', product_name)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/summary${params.toString() ? `?${params.toString()}` : ''}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取按 SOP 汇总失败')
  const body = await res.json()
  return (body.data?.items || []) as SopSummaryItem[]
}

export async function fetchTestTaskDetail(id: string): Promise<TestTaskDetail> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${id}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error(res.status === 404 ? '任务不存在或已删除' : '获取检验任务详情失败')
  const body = await res.json()
  return body.data as TestTaskDetail
}

export async function updateTestResults(
  taskId: string,
  results: { result_id: string; result_text?: string | null; result_value?: number | null; is_pass?: boolean | null }[],
): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/results`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ results }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存结果失败')
  }
  return res.json()
}

export async function addTestResult(
  taskId: string,
  data: { item_name: string; category?: string; sop_no?: string; standard_text?: string; operator?: string; limit_min?: number | null; limit_max?: number | null; method_source?: string; remark?: string },
): Promise<{ message: string; data: TestResultItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/results`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '追加项目失败')
  }
  return res.json()
}

export interface TaskCoaReportItem {
  report_id: string
  filename: string
  file_no: string
  template_path: string
}

export async function generateTaskReports(
  taskId: string,
): Promise<{ message: string; data: TaskCoaReportItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/report`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '生成 COA 失败')
  }
  return res.json()
}

export async function downloadReportFile(reportId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records/${reportId}/download`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('下载报告文件失败')
  return res.blob()
}

/** 报告单在线预览 HTML（服务端 docx→HTML 转换，已鉴权）。 */
export async function fetchReportPreviewHtml(reportId: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records/${reportId}/preview-html`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取报告预览失败')
  return res.text()
}

/** 下载 COA 模板文件（带鉴权；后端端点已加 require_permission）。 */
export async function downloadTemplateFile(path: string): Promise<Blob> {
  const res = await fetch(
    `${API_BASE_URL}/api/v1/quality/templates/${encodeURIComponent(path).replace(/%2F/g, '/')}/download`,
    { headers: await _authHeaders() },
  )
  if (!res.ok) throw new Error('下载模板失败')
  return res.blob()
}

export async function parseLcIntoTask(taskId: string, formData: FormData): Promise<{ message: string; data: TestTaskDetail }> {
  const headers = await _authHeaders()
  delete headers['Content-Type']
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/parse-lc`, {
    method: 'POST', headers, body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '解析填入失败')
  }
  return res.json()
}

export async function updateTestTaskStatus(taskId: string, status: TestTaskStatus): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/status`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '状态更新失败')
  }
  revalidatePath('/quality/task')
  return res.json()
}

export async function deleteTestTask(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除检验任务失败')
  revalidatePath('/quality/task')
  return res.json()
}

export async function deleteTestResult(taskId: string, resultId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/results/${resultId}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除结果行失败')
  return res.json()
}

// ─── 不合格事件台账 ───







// ─── 任务原始证据附件 / 双人复核 ───

export async function fetchTaskAttachments(taskId: string): Promise<{ data: TaskAttachment[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/attachments`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取附件列表失败')
  return res.json()
}

export async function uploadTaskAttachment(taskId: string, formData: FormData): Promise<{ message: string; data: { id: string; filename: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/attachments`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '上传附件失败')
  }
  return res.json()
}

export async function downloadTaskAttachment(taskId: string, attachmentId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/attachments/${attachmentId}/download`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('下载附件失败')
  return res.blob()
}

export async function deleteTaskAttachment(taskId: string, attachmentId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/attachments/${attachmentId}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除附件失败')
  return res.json()
}

export async function fetchTaskReviews(taskId: string): Promise<{ data: TaskReviewRecord[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/reviews`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取复核记录失败')
  return res.json()
}

export async function approveTaskReview(taskId: string, comment?: string): Promise<{
  message: string
  data: TestTaskDetail & { approved_count: number; review_required: number }
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/review`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ comment }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '复核失败')
  }
  return res.json()
}

export async function fetchSummaryMatrix(
  product_name?: string, date_from?: string, date_to?: string, include_in_progress?: boolean,
): Promise<{ data: SummaryMatrix }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (date_from) qs.set('date_from', date_from)
  if (date_to) qs.set('date_to', date_to)
  if (include_in_progress) qs.set('include_in_progress', 'true')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/matrix?${qs.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取汇总矩阵失败')
  return res.json()
}

export async function exportSummaryMatrix(
  product_name?: string, date_from?: string, date_to?: string, include_in_progress?: boolean,
): Promise<Blob> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (date_from) qs.set('date_from', date_from)
  if (date_to) qs.set('date_to', date_to)
  if (include_in_progress) qs.set('include_in_progress', 'true')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/matrix/export?${qs.toString()}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('导出失败')
  return res.blob()
}

export async function fetchItemTrend(
  itemName: string, product_name?: string, limit = 50,
): Promise<{ data: SummaryTrend }> {
  const qs = new URLSearchParams({ item_name: itemName, limit: String(limit) })
  if (product_name) qs.set('product_name', product_name)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/trend?${qs.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取趋势数据失败')
  return res.json()
}

export async function fetchQualityDashboard(): Promise<{ data: QualityDashboard }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/dashboard/summary`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取总览失败')
  return res.json()
}

export async function fetchDailyReports(date?: string, productName?: string): Promise<{ data: DailyReportItem[] }> {
  const qp = new URLSearchParams()
  if (date) qp.set('date', date)
  if (productName) qp.set('product_name', productName)
  const qs = qp.toString() ? `?${qp}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/daily-reports${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取报告单汇总失败')
  return res.json()
}

/** 按月汇总报告单流水（月末归档对账）。 */
export async function fetchMonthlyReports(month?: string, productName?: string): Promise<{ data: MonthlyReportSummary }> {
  const qp = new URLSearchParams()
  if (month) qp.set('month', month)
  if (productName) qp.set('product_name', productName)
  const qs = qp.toString() ? `?${qp}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/monthly-reports${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取月度汇总失败')
  return res.json()
}


// ─── 液相计算表模板配置维护 ───

export async function fetchLcTemplateConfigs(): Promise<{ data: LcTemplateConfig[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取液相模板配置失败')
  return res.json()
}

export async function createLcTemplateConfig(data: {
  table_no: string
  product_name: string
  sop_no?: string
  description?: string
  config: Record<string, unknown>
}): Promise<{ data: { id: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates`, {
    method: 'POST',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '新增模板配置失败')
  }
  return res.json()
}

export async function updateLcTemplateConfig(
  id: string,
  data: Partial<Omit<LcTemplateConfig, 'id' | 'table_no'>>,
): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates/${id}`, {
    method: 'PUT',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新模板配置失败')
  }
  return res.json()
}

export async function deleteLcTemplateConfig(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除模板配置失败')
  return res.json()
}


/** 批号 → 产品代号与标准文件解析（建任务三端统一收敛点）。 */
export async function resolveBatchStandard(
  productName: string,
  batchNumber: string,
): Promise<{
  data: {
    product_code: string | null
    known_codes: string[]
    documents: { id: string; file_no: string; product_code: string | null; specification: string | null; valid_years: string | null }[]
  }
}> {
  const qp = new URLSearchParams({ product_name: productName, batch_number: batchNumber })
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/resolve?${qp}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '批号解析失败')
  }
  return res.json()
}


/** 任务已生成的报告单列表。 */
export async function fetchTaskReports(taskId: string): Promise<{ data: TaskReportItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/reports`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取任务报告单失败')
  return res.json()
}


/** 标准文件当前绑定的 COA 模板（标准文件详情为绑定唯一维护入口）。 */
export async function fetchDocCoaBinding(docId: string): Promise<{
  data: { template_path: string; description: string | null } | null
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${docId}/coa-binding`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取模板绑定失败')
  return res.json()
}

/** 解绑标准文件的 COA 模板。 */
export async function unbindDocCoaBinding(docId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/standards/documents/${docId}/coa-binding`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('解绑失败')
  return res.json()
}


/** 模板路径列表（绑定弹窗用；template:manage 门禁，含各模板当前绑定的 SOP）。 */
export async function fetchTemplatePaths(): Promise<{ data: { path: string; bound_sop_no: string | null }[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/paths`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取模板列表失败')
  return res.json()
}


/** 报告单审核：approve 通过 / reject 退回（含备注）。 */
export async function auditReport(
  reportId: string, action: 'approve' | 'reject', comment?: string,
): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records/${reportId}/audit`, {
    method: 'POST',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, comment }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '审核提交失败')
  }
  return res.json()
}


/** 报告单一致性校验（解析值 vs 填报值、快照 vs 现行标准）。 */
export async function fetchReportConsistency(reportId: string): Promise<{
  data: { parsed_mismatches: { item_name: string; report_value: number; parsed_value: number }[]; standard_drifts: { item_name: string; snapshot_text: string | null; current_text: string | null }[] }
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records/${reportId}/consistency`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取一致性校验失败')
  return res.json()
}


// ─── 物料容器赋码 ───

export async function generateMaterialContainers(input: {
  material_code: string
  material_name: string
  vendor_code?: string
  inbound_batch_no: string
  expiry_date?: string
  count: number
  material_request_id?: string
}): Promise<{ message: string; data: MaterialContainerItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/generate`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '赋码失败')
  }
  return res.json()
}

export async function fetchMaterialContainers(
  page = 1, status?: string, batchNo?: string, materialCode?: string,
): Promise<{ data: MaterialContainerItem[]; meta: { total: number } }> {
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  if (status) params.set('status', status)
  if (batchNo) params.set('batch_no', batchNo)
  if (materialCode) params.set('material_code', materialCode)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers?${params.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取物料容器失败')
  return res.json()
}

export async function moveMaterialContainer(
  containerNo: string, opType: 'in' | 'out' | 'auto' | 'return', relatedDoc?: string, remark?: string,
): Promise<{ message: string; data: MaterialContainerItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/${containerNo}/move`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ op_type: opType, related_doc: relatedDoc, remark }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '操作失败')
  }
  return res.json()
}

export async function updateMaterialContainerStatus(
  containerNo: string, status: 'in_warehouse' | 'qualified' | 'void', remark?: string,
): Promise<{ message: string; data: MaterialContainerItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/${containerNo}/status`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' }, body: JSON.stringify({ status, remark }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '状态变更失败')
  }
  return res.json()
}

export async function downloadContainerLabels(containerNos: string[], reprint = false): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/label`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ container_nos: containerNos, reprint }),
  })
  if (!res.ok) throw new Error('标签生成失败')
  return res.blob()
}

export async function batchMoveMaterialContainers(
  containerNos: string[], opType: 'in' | 'out',
): Promise<{ message: string; data: { results: { container_no: string; ok: boolean; detail?: string }[]; updated: number; failed: number } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/batch-move`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ container_nos: containerNos, op_type: opType }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '批量操作失败')
  }
  return res.json()
}


// ─── 物料字典 / 库存概览 / 台账 ───

export async function fetchMaterialDict(q?: string, page = 1): Promise<{ data: MaterialDictItem[]; meta: { total: number } }> {
  const params = new URLSearchParams({ page: String(page), page_size: '50' })
  if (q) params.set('q', q)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/dict?${params.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取物料字典失败')
  return res.json()
}

export async function createMaterialDict(input: {
  code: string; name: string; category?: string; vendor_name?: string; pack_spec?: string; min_stock?: number; valid_months?: number; remark?: string
}): Promise<{ message: string; data: MaterialDictItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/dict`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '新增物料失败')
  }
  return res.json()
}

export async function updateMaterialDict(id: string, input: Partial<{
  name: string; category: string; vendor_name: string; pack_spec: string; min_stock: number; remark: string
}>): Promise<{ message: string; data: MaterialDictItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/dict/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新物料失败')
  }
  return res.json()
}

export async function deleteMaterialDict(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/dict/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除物料失败')
  return res.json()
}

export async function fetchMaterialSummary(): Promise<{ data: MaterialSummaryItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/summary`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取库存概览失败')
  return res.json()
}

export async function fetchMaterialMovements(
  page = 1, materialQ?: string, opType?: string,
): Promise<{ data: MaterialMovementItem[]; meta: { total: number } }> {
  const params = new URLSearchParams({ page: String(page), page_size: '50' })
  if (materialQ) params.set('material_q', materialQ)
  if (opType) params.set('op_type', opType)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/movements?${params.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取台账失败')
  return res.json()
}

export async function exportMaterialMovements(materialQ?: string, opType?: string): Promise<Blob> {
  const params = new URLSearchParams()
  if (materialQ) params.set('material_q', materialQ)
  if (opType) params.set('op_type', opType)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/movements/export${qs}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('台账导出失败')
  return res.blob()
}


// ─── 采购建议 ───

export async function fetchPurchaseSuggestions(): Promise<{ data: PurchaseSuggestion[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/purchase-suggestions`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取采购建议失败')
  return res.json()
}

export async function exportPurchaseSuggestions(): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/purchase-suggestions/export`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('采购建议导出失败')
  return res.blob()
}


export async function fetchContainerDetail(containerNo: string): Promise<{ data: { container: MaterialContainerItem; movements: MaterialMovementItem[] } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/${encodeURIComponent(containerNo)}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取容器详情失败')
  return res.json()
}

export async function fetchMaterialTodayStats(): Promise<{ data: { today_in: number; today_out: number } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/today-stats`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取今日统计失败')
  return res.json()
}

export async function fetchMaterialTrend(materialCode: string, months = 6): Promise<{
  data: { trend: { month: string; in: number; out: number }[]; monthly_avg_out: number; suggested_min_stock: number | null }
}> {
  const params = new URLSearchParams({ material_code: materialCode, months: String(months) })
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/trend?${params.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取领用趋势失败')
  return res.json()
}


// ─── 供应商主数据 ───

export async function fetchSuppliers(q?: string): Promise<{ data: SupplierItem[] }> {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/suppliers${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取供应商失败')
  return res.json()
}

export async function createSupplier(input: {
  code: string; name: string; contact?: string; phone?: string; qual_expiry_date?: string; remark?: string
}): Promise<{ message: string; data: SupplierItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/suppliers`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '新增供应商失败')
  }
  return res.json()
}

export async function updateSupplier(id: string, input: Partial<{
  name: string; contact: string; phone: string; qual_expiry_date: string; remark: string
}>): Promise<{ message: string; data: SupplierItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/suppliers/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新供应商失败')
  }
  return res.json()
}

export async function deleteSupplier(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/suppliers/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除供应商失败')
  return res.json()
}


// ─── 盘点与月度报表 ───

export async function createStocktake(input: { scope_material_code?: string; remark?: string }): Promise<{ message: string; data: StocktakeSheet }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '创建盘点单失败')
  }
  return res.json()
}

export async function fetchStocktakes(status?: string): Promise<{ data: StocktakeSheet[] }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取盘点单失败')
  return res.json()
}

export async function scanStocktake(sheetId: string, containerNo: string): Promise<{ message: string; data: StocktakeItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes/${sheetId}/scan`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ container_no: containerNo }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '盘点扫码失败')
  }
  return res.json()
}

export async function finishStocktake(sheetId: string): Promise<{ message: string; data: StocktakeSheet }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes/${sheetId}/finish`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '结束盘点失败')
  }
  return res.json()
}

export async function fetchStocktakeDetail(sheetId: string): Promise<{
  data: { sheet: StocktakeSheet; items: StocktakeItem[]; missing: { container_no: string; material_name: string; material_code: string; status: string }[] }
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes/${sheetId}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取盘点详情失败')
  return res.json()
}

export async function exportStocktake(sheetId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/stocktakes/${sheetId}/export`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('盘点导出失败')
  return res.blob()
}

export async function fetchMonthlyReport(month: string): Promise<{ data: MonthlyReportItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/monthly-report?month=${encodeURIComponent(month)}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取月度报表失败')
  return res.json()
}

export async function exportMonthlyReport(month: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/monthly-report/export?month=${encodeURIComponent(month)}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('月度报表导出失败')
  return res.blob()
}


// ─── 导入 / 库位 / 呆滞 ───

export async function downloadImportTemplate(kind: 'dict' | 'containers'): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/import-template?kind=${kind}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('模板下载失败')
  return res.blob()
}

export async function importMaterialDict(file: File): Promise<{ message: string; data: { created: string[]; skipped: string[] } }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/dict/import`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '物料字典导入失败')
  }
  return res.json()
}

export async function importMaterialContainers(file: File): Promise<{ message: string; data: { created: string[]; skipped: string[] } }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/import`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '容器导入失败')
  }
  return res.json()
}

export async function fetchSlowMoving(minAge = 30): Promise<{ data: { items: SlowMovingItem[]; total: number } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/slow-moving?min_age=${minAge}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取呆滞库存失败')
  return res.json()
}

export async function updateContainerLocation(containerNo: string, location: string): Promise<{ message: string; data: MaterialContainerItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/containers/${containerNo}/location`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ location }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '库位更新失败')
  }
  return res.json()
}


// ─── 物料请验与放行 ───

export async function createMaterialRequest(input: {
  material_code: string; vendor_code?: string; inbound_batch_no: string; inbound_qty: number; inbound_date?: string
}): Promise<{ message: string; data: MaterialRequestItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/requests`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '创建请验单失败')
  }
  return res.json()
}

export async function fetchMaterialRequests(status?: string, batchNo?: string): Promise<{ data: MaterialRequestItem[] }> {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (batchNo) params.set('batch_no', batchNo)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/requests${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取请验单失败')
  return res.json()
}

export async function sampleMaterialRequest(id: string, input: { sampled_qty?: number; sampled_at?: string }): Promise<{ message: string; data: MaterialRequestItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/requests/${id}/sample`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '取样登记失败')
  }
  return res.json()
}

export async function createMaterialInspectionTask(id: string): Promise<{ message: string; data: { task_id: string; batch_number: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/requests/${id}/task`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '建检验任务失败')
  }
  return res.json()
}

export async function releaseMaterialRequest(id: string, verdict: 'release' | 'reject' | 'concede', remark?: string): Promise<{ message: string; data: MaterialRequestItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/requests/${id}/release`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ verdict, remark }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '放行操作失败')
  }
  return res.json()
}

export async function createMaterialStandard(input: { material_code: string; vendor_code?: string; version?: string }): Promise<{ message: string; data: MaterialStandardRow }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/standards`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '创建物料标准失败')
  }
  return res.json()
}

export async function fetchMaterialStandardItems(standardId: string): Promise<{ data: MaterialStandardItemRow[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/standards/${standardId}/items`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取标准项目失败')
  return res.json()
}

export async function createMaterialStandardItem(standardId: string, input: Partial<MaterialStandardItemRow>): Promise<{ message: string; data: MaterialStandardItemRow }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/material/standards/${standardId}/items`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...input, standard_id: standardId }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '添加项目行失败')
  }
  return res.json()
}

export async function fetchDashboardTrend(days = 7): Promise<{ data: { date: string; reports: number; completed_tasks: number }[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/dashboard/trend?days=${days}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取看板趋势失败')
  return res.json()
}


// ─── 试剂/仪器台账与请检计划 ───

export async function fetchLabItems(itemType?: string, q?: string): Promise<{ data: LabItem[] }> {
  const params = new URLSearchParams()
  if (itemType) params.set('item_type', itemType)
  if (q) params.set('q', q)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lab-items${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取台账失败')
  return res.json()
}

export async function createLabItem(input: Partial<LabItem>): Promise<{ message: string; data: LabItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lab-items`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '新增失败')
  }
  return res.json()
}

export async function updateLabItem(id: string, input: Partial<LabItem>): Promise<{ message: string; data: LabItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lab-items/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error('更新失败')
  return res.json()
}

export async function deleteLabItem(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lab-items/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}

export async function fetchInspectionPlans(date?: string, department?: string): Promise<{ data: InspectionPlan[] }> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (department) params.set('department', department)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取请检计划失败')
  return res.json()
}

export async function createInspectionPlan(input: Partial<InspectionPlan>): Promise<{ message: string; data: InspectionPlan }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '新增失败')
  }
  return res.json()
}

export async function updateInspectionPlanStatus(id: string, status: 'pending' | 'inspected', plan_time?: string): Promise<{ message: string; data: InspectionPlan }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans/${id}/status`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, plan_time }),
  })
  if (!res.ok) throw new Error('状态更新失败')
  return res.json()
}

export async function importInspectionPlans(file: File): Promise<{ message: string; data: { created: string[]; skipped: string[] } }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans/import`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '导入失败')
  }
  return res.json()
}

export async function downloadInspectionPlanTemplate(): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans/template`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('模板下载失败')
  return res.blob()
}


// ─── 微生物限度/菌落计数登记 ───

export async function fetchMicroRecords(batchNo?: string): Promise<{ data: MicroRecord[] }> {
  const params = new URLSearchParams()
  if (batchNo) params.set('batch_no', batchNo)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取登记失败')
  return res.json()
}

export async function createMicroRecord(input: Partial<MicroRecord>): Promise<{ message: string; data: MicroRecord }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存失败')
  }
  return res.json()
}

export async function updateMicroRecord(id: string, input: Partial<MicroRecord>): Promise<{ message: string; data: MicroRecord }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error('更新失败')
  return res.json()
}

export async function deleteMicroRecord(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}

export async function uploadMicroPhotos(recordId: string, files: File[]): Promise<{ message: string; data: { photo_keys: string[] } }> {
  const formData = new FormData()
  for (const f of files) formData.append('files', f)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records/${recordId}/photos`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '照片上传失败')
  }
  return res.json()
}

export async function fetchMicroPhotoDataUrl(recordId: string, key: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records/${recordId}/photos/${encodeURIComponent(key)}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('照片加载失败')
  const blob = await res.blob()
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve(reader.result as string)
    reader.readAsDataURL(blob)
  })
}

export async function exportMicroRecords(batchNo?: string): Promise<Blob> {
  const params = new URLSearchParams()
  if (batchNo) params.set('batch_no', batchNo)
  const qs = params.toString() ? `?${params}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/micro-records/export${qs}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('导出失败')
  return res.blob()
}


// ─── 留样台账 ───

export async function fetchRetainedSamples(params?: {
  sourceType?: string; batchNo?: string; status?: string
}): Promise<{ data: RetainedSample[] }> {
  const q = new URLSearchParams()
  if (params?.sourceType) q.set('source_type', params.sourceType)
  if (params?.batchNo) q.set('batch_no', params.batchNo)
  if (params?.status) q.set('status', params.status)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取留样台账失败')
  return res.json()
}

export async function createRetainedSample(input: Partial<RetainedSample>): Promise<{ message: string; data: RetainedSample }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '留样登记失败')
  }
  revalidatePath('/quality/retained')
  return res.json()
}

export async function updateRetainedSample(id: string, input: Partial<RetainedSample>): Promise<{ message: string; data: RetainedSample }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '更新失败')
  }
  revalidatePath('/quality/retained')
  return res.json()
}

export async function destroyRetainedSample(id: string, input: { destroyed_at: string; remark?: string }): Promise<{ message: string; data: RetainedSample }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples/${id}/destroy`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '销毁登记失败')
  }
  revalidatePath('/quality/retained')
  return res.json()
}

export async function deleteRetainedSample(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  revalidatePath('/quality/retained')
  return res.json()
}

export async function exportRetainedSamples(params?: {
  sourceType?: string; batchNo?: string; status?: string
}): Promise<Blob> {
  const q = new URLSearchParams()
  if (params?.sourceType) q.set('source_type', params.sourceType)
  if (params?.batchNo) q.set('batch_no', params.batchNo)
  if (params?.status) q.set('status', params.status)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/retained-samples/export${qs}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('导出失败')
  return res.blob()
}


// ─── 环境监测 ───

export async function fetchEnvPoints(params?: {
  room?: string; monitorType?: string; status?: string; keyword?: string
}): Promise<{ data: EnvPoint[] }> {
  const q = new URLSearchParams()
  if (params?.room) q.set('room', params.room)
  if (params?.monitorType) q.set('monitor_type', params.monitorType)
  if (params?.status) q.set('status', params.status)
  if (params?.keyword) q.set('keyword', params.keyword)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/points${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取监测点失败')
  return res.json()
}

export async function createEnvPoint(input: Partial<EnvPoint>): Promise<{ message: string; data: EnvPoint }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/points`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '监测点保存失败')
  }
  revalidatePath('/quality/env')
  return res.json()
}

export async function updateEnvPoint(id: string, input: Partial<EnvPoint>): Promise<{ message: string; data: EnvPoint }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/points/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '监测点更新失败')
  }
  revalidatePath('/quality/env')
  return res.json()
}

export async function deleteEnvPoint(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/points/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  revalidatePath('/quality/env')
  return res.json()
}

export async function fetchEnvRecords(params?: {
  pointId?: string; judge?: string; dateFrom?: string; dateTo?: string; handleStatus?: string
}): Promise<{ data: EnvRecord[] }> {
  const q = new URLSearchParams()
  if (params?.pointId) q.set('point_id', params.pointId)
  if (params?.judge) q.set('judge', params.judge)
  if (params?.dateFrom) q.set('date_from', params.dateFrom)
  if (params?.dateTo) q.set('date_to', params.dateTo)
  if (params?.handleStatus) q.set('handle_status', params.handleStatus)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取监测记录失败')
  return res.json()
}

export async function createEnvRecord(input: {
  point_id: string; record_date: string; result_value: number | null; remark?: string
}): Promise<{ message: string; data: EnvRecord | null }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '记录保存失败')
  }
  revalidatePath('/quality/env')
  return res.json()
}

export async function deleteEnvRecord(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  revalidatePath('/quality/env')
  return res.json()
}

export async function exportEnvRecords(params?: {
  pointId?: string; judge?: string; dateFrom?: string; dateTo?: string
}): Promise<Blob> {
  const q = new URLSearchParams()
  if (params?.pointId) q.set('point_id', params.pointId)
  if (params?.judge) q.set('judge', params.judge)
  if (params?.dateFrom) q.set('date_from', params.dateFrom)
  if (params?.dateTo) q.set('date_to', params.dateTo)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records/export${qs}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('导出失败')
  return res.blob()
}

export async function fetchEnvTrend(pointId: string, days = 90): Promise<{ data: EnvTrend }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/trend?point_id=${pointId}&days=${days}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取趋势失败')
  return res.json()
}

export async function fetchEnvPlans(date?: string): Promise<{ data: { date: string; items: EnvPlan[] } }> {
  const q = date ? `?date=${encodeURIComponent(date)}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/plans${q}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取周期计划失败')
  return res.json()
}

export async function handleEnvRecord(recordId: string, input: { handled_remark?: string }): Promise<{ message: string; data: EnvRecord }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records/${recordId}/handle`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '标记处理失败')
  }
  revalidatePath('/quality/env')
  revalidatePath('/quality/dashboard')
  return res.json()
}

export async function testCalc(tableNo: string, section: number, inputs: Record<string, number | undefined>): Promise<{ data: { items: { label: string; std_name: string; value: number | null; nd?: boolean; detail?: string }[] } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/test-calc`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ table_no: tableNo, section, inputs, values: [] }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '测试计算失败')
  }
  return res.json()
}

export async function fetchBatchReleases(params?: { batchNo?: string; status?: string }): Promise<{ data: BatchRelease[] }> {
  const q = new URLSearchParams()
  if (params?.batchNo) q.set('batch_no', params.batchNo)
  if (params?.status) q.set('status', params.status)
  const qs = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/release-records${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取放行记录失败')
  return res.json()
}

export async function createBatchRelease(input: { task_id: string; remark?: string }): Promise<{ message: string; data: BatchRelease }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/release-records`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '发起放行失败')
  }
  revalidatePath('/quality/release')
  return res.json()
}

export async function releaseBatchRecord(id: string, input: { release_remark?: string }): Promise<{ message: string; data: BatchRelease }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/release-records/${id}/release`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '放行失败')
  }
  revalidatePath('/quality/release')
  return res.json()
}

export async function fetchPersonnel(keyword?: string): Promise<{ data: { items: PersonnelItem[]; total: number } }> {
  const q = new URLSearchParams()
  if (keyword) q.set('keyword', keyword)
  q.set('limit', '200')
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/personnel?${q.toString()}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取人员名单失败')
  return res.json()
}

export async function fetchTaskAssignments(taskId: string): Promise<{ data: TaskAssignment[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/assignments`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取分工失败')
  return res.json()
}

export async function saveTaskAssignments(taskId: string, assignments: { sop_no: string; assignee_id: string }[]): Promise<{ message: string; data: TaskAssignment[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/assignments`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ assignments }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存分工失败')
  }
  revalidatePath('/quality/board')
  return res.json()
}

export interface ShiftTeamItem {
  id: string
  name: string
  group_key: string
  member_ids: string[]
  member_names: string[]
  seq: number
  remark: string | null
}

export async function fetchShiftTeams(): Promise<{ data: ShiftTeamItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/teams`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取班组失败')
  return res.json()
}

export async function createShiftTeam(input: { name: string; group_key?: string; member_ids: string[]; seq: number; remark?: string }): Promise<{ message: string; data: { id: string; name: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/teams`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存班组失败')
  }
  revalidatePath('/quality/board')
  return res.json()
}

export async function updateShiftTeam(id: string, input: { name: string; group_key?: string; member_ids: string[]; seq: number; remark?: string }): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/teams/${id}`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error('更新班组失败')
  revalidatePath('/quality/board')
  return res.json()
}

export async function deleteShiftTeam(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/teams/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除班组失败')
  revalidatePath('/quality/board')
  return res.json()
}

export async function fetchShiftConfig(): Promise<{ data: { start_date: string | null; period_days: number; duty_teams: number; team_order: string[] | null } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/config`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取轮换配置失败')
  return res.json()
}

export async function saveShiftConfig(input: { start_date: string; period_days: number; duty_teams: number; team_order?: string[]; group?: string }): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/config`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error('保存轮换配置失败')
  revalidatePath('/quality/board')
  return res.json()
}

export interface ShiftGroupData {
  groups: { group: string; configured: boolean; teams: { id: string; name: string }[]; members: { id: string; name: string }[]; all_members: { id: string; name: string }[] }[]
  mapping: Record<string, string[]>
}

export async function fetchShiftGroups(): Promise<{ data: ShiftGroupData; meta?: { scope_groups?: string[] } | null }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/groups`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取组别失败')
  return res.json()
}

export async function saveShiftItemGroups(mapping: Record<string, string[]>): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/item-groups`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(mapping),
  })
  if (!res.ok) throw new Error('保存组别映射失败')
  revalidatePath('/quality/board')
  return res.json()
}

export async function fetchShiftDuty(): Promise<{ data: { date: string; configured: boolean; teams: { id: string; name: string }[]; members: { id: string; name: string }[] } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/shift/duty`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取当班信息失败')
  return res.json()
}

export async function fetchPlanBoard(): Promise<{ data: PlanBoardItem[]; meta?: { scope_groups?: string[] } | null }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/plans/board`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取排班看板失败')
  return res.json()
}

export async function savePlanAssignments(planId: string, assignments: { sop_no: string; assignee_id: string }[]): Promise<{ message: string; data: PlanBoardItem }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans/${planId}/assignments`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ assignments }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '排班保存失败')
  }
  revalidatePath('/quality/board')
  return res.json()
}

export async function notifyPlanAssignments(planId: string): Promise<{ message: string; data: { notified: number; skipped: number } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/inspection-plans/${planId}/notify`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '排班通知下发失败')
  }
  revalidatePath('/quality/board')
  return res.json()
}

export async function fetchTaskBoard(status?: string): Promise<{ data: BoardTask[] }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/board${q}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取任务看板失败')
  return res.json()
}

export async function fetchDashboardAlerts(): Promise<{ data: QualityAlerts }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/dashboard/alerts`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取提醒中心失败')
  return res.json()
}

export async function submitCalcFill(taskId: string, input: {
  table_no?: string; record_date?: string
  values?: { item_name: string; value: number }[]
  inputs?: Record<string, number | undefined>
  section?: number
}): Promise<{ message: string; data: { filled: string[]; unmatched: string[] } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/calc-fill`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '计算表提交失败')
  }
  revalidatePath(`/quality/task/${taskId}`)
  return res.json()
}

/** 傻瓜式维护：上传计算表自动识别同版式模板（返回候选，无需会写 JSON）。 */
export async function autoDetectTemplate(file: File, password?: string): Promise<{
  data: { table_no: string; candidates: { template_table_no: string; product_name: string; description: string; component_count: number; value_count: number; samples: { name: string; value: number | null }[] }[] }
}> {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates/auto-detect`, {
    method: 'POST', headers: await _authHeaders(), body: form,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '自动识别失败')
  }
  return res.json()
}

/** 傻瓜式维护：按同版式模板一键生成新表号配置。 */
export async function autoCreateTemplate(table_no: string, template_table_no: string): Promise<{ message: string; data: { id: string; table_no: string } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/templates/auto-create`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ table_no, template_table_no }),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '生成配置失败')
  }
  return res.json()
}

/** 确认解析自动填入的结果（正式归入；确认后参与自动流转）。 */
export async function confirmTaskResult(taskId: string, resultId: string, value?: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/results/${resultId}/confirm`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(value !== undefined ? { result_value: value } : {}),
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '确认失败')
  }
  revalidatePath(`/quality/task/${taskId}`)
  return res.json()
}

/** 图谱截图/PDF 解析（MinerU VLM，仅预览：返回峰表草稿，不落库）。 */
export async function parseChromatogram(file: File): Promise<{ data: { filename: string; peaks: ChromatogramPeak[]; markdown_preview: string } }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/chromatograms/parse`, {
    method: 'POST', headers: await _authHeaders(), body: form,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '图谱解析失败')
  }
  return res.json()
}

export async function downloadEnvImportTemplate(type: 'points' | 'records'): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/import-template?type=${type}`, {
    headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('模板下载失败')
  return res.blob()
}

export async function importEnvPoints(file: File): Promise<{ message: string; data: { created: number; skipped: number; errors: { row: number; reason: string }[] } }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/points/import`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '导入失败')
  }
  revalidatePath('/quality/env')
  return res.json()
}

export async function importEnvRecords(file: File): Promise<{ message: string; data: { created: number; errors: { row: number; reason: string }[] } }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/env/records/import`, {
    method: 'POST', headers: await _authHeaders(), body: formData,
  })
  if (!res.ok) {
    const err: ApiErrorBody = await res.json().catch(() => ({}))
    throw new Error(err.detail || '导入失败')
  }
  revalidatePath('/quality/env')
  return res.json()
}


export async function fetchTaskHandover(taskId: string): Promise<{ data: {
  task_id: string; product_name: string; batch_number: string; status: string
  production_date: string | null; report_date: string | null
  filled: number; total: number; unfilled: string[]
  items: { name: string; value: string | number; verdict: string }[]
  reports: { serial_no: string | null; filename: string | null }[]
} }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/handover`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取交接汇总失败')
  return res.json()
}
