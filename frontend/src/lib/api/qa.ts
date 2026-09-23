'use client'

import { apiFetchPaginated, apiGet } from '@/lib/http-client'
import type {
  QaAuditLog,
  QaAiAnalysisRun,
  QaDepartmentReference,
  QaDocument,
  QaDocumentProcessingResult,
  QaDocumentProcessingView,
  QaDocumentSort,
  QaDocumentType,
  QaMasterKind,
  QaMasterObject,
  QaPage,
  QaSearchPage,
  QaSearchResult,
  QaMasterObjectProposal,
  QaSourceReference,
} from '@/types/qa'

// 浏览器优先走 Next rewrite，避免跨端口时 httpOnly auth cookie 丢失；
// 服务端调用再使用显式后端地址。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const QA_BASE = `${API_BASE}/api/v1/qa`

function qs(params: Record<string, string | number | boolean | undefined | null | string[]>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, item))
      return
    }
    search.set(key, String(value))
  })
  return search.toString()
}

/** 兼容后端直接返回数组或 {items: []} 的非分页引用接口。 */
function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object' && Array.isArray((value as { items?: unknown }).items)) {
    return (value as { items: T[] }).items
  }
  return []
}

/** 分页接口统一适配 { data, meta } 和 data={items,total} 两种响应。 */
function asPage<T>(value: QaPage<T> | T[] | unknown): QaPage<T> {
  if (value && typeof value === 'object') {
    const candidate = value as Partial<QaPage<T>> & { data?: unknown }
    if (Array.isArray(candidate.items)) {
      return {
        items: candidate.items,
        total: Number(candidate.total ?? candidate.items.length),
        page: Number(candidate.page ?? 1),
        page_size: Number(candidate.page_size ?? (candidate.items.length || 20)),
      }
    }
    // 某些部署版本会将分页对象再包在 data.items 中；保留兼容读取。
    if (candidate.items && typeof candidate.items === 'object' && Array.isArray((candidate.items as { items?: unknown }).items)) {
      const nested = candidate.items as { items: T[]; total?: number; page?: number; page_size?: number }
      return {
        items: nested.items,
        total: Number(nested.total ?? candidate.total ?? nested.items.length),
        page: Number(nested.page ?? candidate.page ?? 1),
        page_size: Number(nested.page_size ?? candidate.page_size ?? (nested.items.length || 20)),
      }
    }
  }
  const items = asArray<T>(value)
  return { items, total: items.length, page: 1, page_size: items.length || 20 }
}

export async function fetchQaMasterObjects(params: {
  kind?: QaMasterKind
  keyword?: string
  include_inactive?: boolean
  page?: number
  page_size?: number
} = {}): Promise<QaPage<QaMasterObject>> {
  const query = qs({
    kind: params.kind,
    keyword: params.keyword,
    include_inactive: params.include_inactive,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  })
  const result = await apiFetchPaginated<QaMasterObject>(`${QA_BASE}/master-objects?${query}`)
  return asPage(result)
}

export async function fetchQaMasterObject(id: string): Promise<QaMasterObject> {
  return apiGet<QaMasterObject>(`${QA_BASE}/master-objects/${id}`)
}

export async function fetchQaDepartments(params: { keyword?: string; include_inactive?: boolean } = {}): Promise<QaDepartmentReference[]> {
  const query = qs(params)
  const result = await apiGet<unknown>(`${QA_BASE}/references/departments${query ? `?${query}` : ''}`)
  return asArray<QaDepartmentReference>(result)
}

export async function fetchQaSources(kind: QaMasterKind, params: { keyword?: string; page?: number; page_size?: number } = {}): Promise<QaPage<QaSourceReference>> {
  const query = qs({
    keyword: params.keyword,
    page: params.page ?? 1,
    page_size: params.page_size ?? 50,
  })
  try {
    const result = await apiFetchPaginated<QaSourceReference>(`${QA_BASE}/references/sources/${kind.toLowerCase()}?${query}`)
    return asPage(result)
  } catch {
    // 后端可能使用大写 kind 作为路由参数，兼容两种约定。
    const result = await apiFetchPaginated<QaSourceReference>(`${QA_BASE}/references/sources/${kind}?${query}`)
    return asPage(result)
  }
}

export async function fetchQaDocumentTypes(params: { include_inactive?: boolean } = {}): Promise<QaDocumentType[]> {
  const query = qs(params)
  const result = await apiGet<unknown>(`${QA_BASE}/document-types${query ? `?${query}` : ''}`)
  return asArray<QaDocumentType>(result)
}

export async function fetchQaDocuments(params: {
  keyword?: string
  document_type_id?: string
  responsible_department_id?: string
  include_inactive?: boolean
  include_history?: boolean
  /** 按“是否已设当前版本”过滤；配合 page_size=1 时 total 即该口径的文件数 */
  has_current_version?: boolean
  /** 排序字段，后端白名单外的值回落到编号 */
  sort_by?: QaDocumentSort
  page?: number
  page_size?: number
} = {}): Promise<QaPage<QaDocument>> {
  const query = qs({
    keyword: params.keyword,
    document_type_id: params.document_type_id,
    responsible_department_id: params.responsible_department_id,
    include_inactive: params.include_inactive,
    include_history: params.include_history,
    has_current_version: params.has_current_version,
    sort_by: params.sort_by,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  })
  const result = await apiFetchPaginated<QaDocument>(`${QA_BASE}/documents?${query}`)
  return asPage(result)
}

export async function fetchQaDocument(id: string): Promise<QaDocument> {
  return apiGet<QaDocument>(`${QA_BASE}/documents/${id}`)
}

export async function fetchQaDocumentProcessingResults(
  fileId: string,
  params: {
    view: QaDocumentProcessingView
    page?: number
    page_size?: number
    content_limit?: number
  },
): Promise<QaDocumentProcessingResult> {
  const query = qs({
    view: params.view,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
    content_limit: params.content_limit ?? 800,
  })
  return apiGet<QaDocumentProcessingResult>(`${QA_BASE}/document-files/${fileId}/processing-results?${query}`)
}

export async function fetchQaAiAnalysis(versionId: string): Promise<QaAiAnalysisRun> {
  return apiGet<QaAiAnalysisRun>(`${QA_BASE}/document-versions/${versionId}/ai-analysis/latest`)
}

export async function fetchQaAiAnalysisRun(runId: string): Promise<QaAiAnalysisRun> {
  return apiGet<QaAiAnalysisRun>(`${QA_BASE}/ai-analysis/${runId}`)
}

export async function fetchQaMasterObjectProposals(params: { status?: string; page?: number; page_size?: number } = {}): Promise<QaPage<QaMasterObjectProposal>> {
  const query = qs({ status: params.status, page: params.page ?? 1, page_size: params.page_size ?? 50 })
  const result = await apiFetchPaginated<QaMasterObjectProposal>(`${QA_BASE}/master-object-proposals?${query}`)
  return asPage(result)
}

export async function fetchQaSearch(params: {
  q: string
  include_history?: boolean
  include_inactive?: boolean
  page?: number
  page_size?: number
}): Promise<QaSearchPage> {
  const query = qs({
    q: params.q,
    keyword: params.q,
    include_history: params.include_history,
    include_inactive: params.include_inactive,
    page: params.page ?? 1,
    page_size: params.page_size ?? 30,
  })
  // 使用分页客户端保留后端 meta.total/page 等信息；asPage 继续兼容旧版 results/数组响应。
  const result = await apiFetchPaginated<QaSearchResult>(`${QA_BASE}/search?${query}`)
  if (result && typeof result === 'object' && Array.isArray((result as { items?: unknown }).items)) {
    return asPage<QaSearchResult>(result) as QaSearchPage
  }
  return asPage<QaSearchResult>(result) as QaSearchPage
}

export async function fetchQaAuditLogs(params: {
  action?: string
  object_type?: string
  actor_id?: string
  from?: string
  to?: string
  page?: number
  page_size?: number
} = {}): Promise<QaPage<QaAuditLog>> {
  const query = qs({
    action: params.action,
    resource_type: params.object_type,
    user_id: params.actor_id,
    from: params.from,
    to: params.to,
    page: params.page ?? 1,
    page_size: params.page_size ?? 50,
  })
  const result = await apiFetchPaginated<QaAuditLog>(`${QA_BASE}/audit-logs?${query}`)
  return asPage(result)
}

export function qaFileContentUrl(fileId: string, download = false): string {
  return `${QA_BASE}/document-files/${fileId}/content${download ? '?download=true' : ''}`
}

export function qaMasterKindLabel(kind: string | null | undefined): string {
  const labels: Record<string, string> = {
    PRODUCT: '产品', MATERIAL: '物料', EQUIPMENT: '设备', SUPPLIER: '供应商', REGION: '区域',
    master_object: '主数据', master: '主数据', document: '文件', document_segment: '文件正文', department: '部门',
  }
  return labels[kind ?? ''] ?? kind ?? '—'
}
