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
} from '@/types/quality'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || (err as any).message || '上传解析失败')
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
): Promise<{ data: ReportRecord[]; meta: { total: number } }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (batch_number) qs.set('batch_number', batch_number)
  qs.set('page', String(page))
  qs.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取报告单记录失败')
  return res.json()
}

/** 生成报告单（返回原始响应，调用方按 blob 下载） */
export async function generateReport(recordId: string, template: string): Promise<Response> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/generate`, {
    method: 'POST',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ inspection_record_id: recordId, template }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '生成报告单失败')
  }
  return res
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '导入失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '解析失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '确认导入失败')
  }
  return res.json()
}


// ─── 报告模板管理 ───

export async function fetchTemplates(): Promise<any[]> {
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '上传模板失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '删除文件夹失败')
  }
  return res.json()
}

export async function bindTemplate(
  template_path: string, standard_document_id: string,
): Promise<{ message: string; data: { template_path: string; sop_no: string | null; standard_document_id: string | null } }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/templates/bindings`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_path, standard_document_id }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '绑定模板失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '删除模板失败')
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
  standard_document_id?: string
  standard_document_ids?: string[]
  standard_item_ids?: string[]
}): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks`, {
    method: 'POST', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '创建检验任务失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '更新出报日期失败')
  }
  revalidatePath('/quality/task')
  return res.json()
}

export async function fetchTestTasks(
  product_name?: string, status?: TestTaskStatus, page = 1,
): Promise<{ data: TestTaskListItem[]; meta: { total: number } }> {
  const params = new URLSearchParams()
  if (product_name) params.set('product_name', product_name)
  if (status) params.set('status', status)
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
  if (!res.ok) throw new Error('获取检验任务详情失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '保存结果失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '追加项目失败')
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
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '生成 COA 失败')
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

export async function parseLcIntoTask(taskId: string, formData: FormData): Promise<{ message: string; data: TestTaskDetail }> {
  const headers = await _authHeaders()
  delete headers['Content-Type']
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/parse-lc`, {
    method: 'POST', headers, body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '解析填入失败')
  }
  return res.json()
}

export async function updateTestTaskStatus(taskId: string, status: TestTaskStatus): Promise<{ message: string; data: TestTaskDetail }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/tasks/${taskId}/status`, {
    method: 'PUT', headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '状态更新失败')
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
