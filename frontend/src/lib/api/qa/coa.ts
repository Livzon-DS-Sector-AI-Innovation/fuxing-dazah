'use client'

import { apiFetchPaginated, apiGet, apiPost, apiPut } from '@/lib/http-client'
import type {
  CoaMatrix,
  CoaProduct,
  CoaProductField,
  CoaRenderRecord,
  CoaReport,
  CoaReportImportPreview,
  CoaRenderCheck,
  CoaStandard,
  CoaStandardImportPreview,
  CoaTemplateAnnotateResult,
  CoaTemplateBindingInput,
  CoaTemplateState,
  CoaVerifyResult,
  QaPage,
} from '@/types/qa'

// 浏览器优先走 Next rewrite；服务端调用使用显式后端地址（与 apr 同口径）。
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const COA_BASE = `${API_BASE}/api/v1/qa/coa`

function qs(
  params: Record<string, string | number | boolean | string[] | undefined | null>
): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((v) => search.append(key, v))
      return
    }
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export async function fetchCoaProducts(activeOnly = false): Promise<CoaProduct[]> {
  return apiGet<CoaProduct[]>(`${COA_BASE}/products${qs({ active_only: activeOnly })}`)
}

export async function fetchCoaProductFields(productId: string): Promise<CoaProductField[]> {
  return apiGet<CoaProductField[]>(`${COA_BASE}/products/${productId}/fields`)
}

export async function fetchCoaStandards(
  productId?: string,
  activeOnly = false
): Promise<CoaStandard[]> {
  return apiGet<CoaStandard[]>(
    `${COA_BASE}/standards${qs({ product_id: productId, active_only: activeOnly })}`
  )
}

export async function fetchCoaStandardDetail(standardId: string): Promise<CoaStandard> {
  return apiGet<CoaStandard>(`${COA_BASE}/standards/${standardId}`)
}

export async function fetchCoaReportDetail(reportId: string): Promise<CoaReport> {
  return apiGet<CoaReport>(`${COA_BASE}/reports/${reportId}`)
}

export async function fetchCoaMatrix(
  productId: string,
  standardIds?: string[]
): Promise<CoaMatrix> {
  return apiGet<CoaMatrix>(
    `${COA_BASE}/reports/matrix${qs({ product_id: productId, standard_id: standardIds })}`
  )
}

/** docx → 客户标准草稿预览（不落库）。客户端直传 FormData（Server Action 有 1MB 限制）。 */
export async function importCoaStandardPreview(file: File): Promise<CoaStandardImportPreview> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${COA_BASE}/standards/import-preview`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `解析失败: ${res.status}` }))
    throw new Error(err.message || `解析失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}

// ─────────────────────── 模板标注与回填 ───────────────────────

/** 文件类请求（FormData / 二进制）不走 http-client：取后端 {message, detail}，带上状态码。 */
async function throwResponseError(res: Response, fallback: string): Promise<never> {
  const body = await res.json().catch(() => null)
  const message = body?.message
  const fallbackMessage = typeof message === 'string' && message ? message : `${fallback}: ${res.status}`
  throw Object.assign(new Error(fallbackMessage), { status: res.status, detail: body?.detail ?? null })
}

/** 模板状态 + 网格 + 已确认的标注（没确认过时 binding 为 null；没上传模板时没有 grid）。 */
export async function fetchCoaTemplate(standardId: string): Promise<CoaTemplateState> {
  return apiGet<CoaTemplateState>(`${COA_BASE}/standards/${standardId}/template`)
}

/** AI 标注：返回给人工核对的提案（不落库）。模型调用通常要半分钟到一分钟。 */
export async function annotateCoaTemplate(standardId: string): Promise<CoaTemplateAnnotateResult> {
  return apiPost<CoaTemplateAnnotateResult>(
    `${COA_BASE}/standards/${standardId}/template/annotate`
  )
}

/** 上传/替换模板 docx；换了文件原标注作废。客户端直传 FormData（Server Action 有 1MB 限制）。 */
export async function uploadCoaTemplate(standardId: string, file: File): Promise<CoaTemplateState> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${COA_BASE}/standards/${standardId}/template`, {
    method: 'PUT',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) await throwResponseError(res, '模板上传失败')
  const json = await res.json()
  return json.data ?? json
}

/** 保存人工确认后的标注（后端会对着模板重新校验一遍）。 */
export async function saveCoaTemplateBinding(
  standardId: string,
  payload: CoaTemplateBindingInput
): Promise<CoaTemplateState> {
  return apiPut<CoaTemplateState>(`${COA_BASE}/standards/${standardId}/template/binding`, payload)
}

/** 生成 COA 的预检：缺项、旧值泄漏（拦截）与警告（缺英文、未标注到模板的项目）。 */
export async function checkCoaRender(reportId: string): Promise<CoaRenderCheck> {
  return apiPost<CoaRenderCheck>(`${COA_BASE}/reports/${reportId}/render?dry_run=true`)
}

/** 生成并取回 COA docx；预检没过时抛 422（error.detail 是预检清单）。 */
export async function downloadCoaRender(reportId: string): Promise<Blob> {
  const res = await fetch(`${COA_BASE}/reports/${reportId}/render`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) await throwResponseError(res, '生成 COA 失败')
  return res.blob()
}

/** 快速打印的地址：在新标签页里直接打开（导航请求自带登录 cookie），由浏览器 PDF 阅读器显示和打印。 */
export function coaPrintUrl(reportId: string): string {
  return `${COA_BASE}/reports/${reportId}/print`
}

// ─────────────────────── 生成留档与验证 ───────────────────────

/** 生成留档列表（新的在前）。 */
export async function fetchCoaRenders(params: {
  product_id?: string | null
  report_id?: string | null
  batch_no?: string
  page?: number
  page_size?: number
} = {}): Promise<QaPage<CoaRenderRecord>> {
  const result = await apiFetchPaginated<CoaRenderRecord>(`${COA_BASE}/renders?${qs(params)}`)
  return { items: result.items, total: result.total, page: result.page, page_size: result.page_size }
}

/** 下载留档的系统原件。 */
export async function downloadCoaRenderFile(recordId: string): Promise<Blob> {
  const res = await fetch(`${COA_BASE}/renders/${recordId}/file`, {
    method: 'GET',
    credentials: 'include',
  })
  if (!res.ok) await throwResponseError(res, '下载系统原件失败')
  return res.blob()
}

/** COA 验证：上传一份 docx，比对系统留档。指定 reportId 时只跟这份报告的留档比。 */
export async function verifyCoaRender(file: File, reportId?: string | null): Promise<CoaVerifyResult> {
  const formData = new FormData()
  formData.append('file', file)
  if (reportId) formData.append('report_id', reportId)
  const res = await fetch(`${COA_BASE}/renders/verify`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) await throwResponseError(res, '验证失败')
  const json = await res.json()
  return json.data ?? json
}
export async function importCoaReportPreview(
  file: File,
  standardId?: string | null
): Promise<CoaReportImportPreview> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(
    `${COA_BASE}/reports/import-preview${qs({ standard_id: standardId })}`,
    { method: 'POST', body: formData, credentials: 'include' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `解析失败: ${res.status}` }))
    throw new Error(err.message || `解析失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}
