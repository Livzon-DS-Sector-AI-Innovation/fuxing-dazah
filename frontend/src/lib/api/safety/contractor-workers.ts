/**
 * 承包商在册人员副台账（3.x 平台关联 F1）API client。
 *
 * 三态信封口径同 domain-pages：live=本次拉取成功（fetched_at=台账时点）；
 * degraded=拉取失败回退旧缓存（fetched_at=缓存时点）；empty=首次失败无缓存。
 * 行内身份证/手机已由后端打码（前 3 后 2），前端不接触明文。
 */
import { apiGet, apiPatch, apiPost, API_BASE_URL } from '@/lib/http-client'

export type ContractorWorkersStatus = 'live' | 'degraded' | 'empty'

export type InsuranceStatus = 'covered' | 'expiring' | 'expired' | 'unfiled' | 'uncovered'

export type CertStatus = 'hit' | 'missing' | 'nonspecial'

export interface ContractorWorkerRow {
  id: string
  name: string
  contractor_name: string
  work_type: string
  age: number | null
  sex?: number | null
  birth_date?: string | null
  join_job_date?: string | null
  card_no_masked: string
  phone_masked: string
  health?: string | null
  education?: string | null
  major?: string | null
  insurance_status: InsuranceStatus
  insurance_expire_date?: string | null
  insurance_days_left?: number | null
  insurance_source_company?: string | null
  cert_status: CertStatus
  cert_project?: string | null
  cert_next_review_date?: string | null
  age_flag: 'red' | 'yellow' | 'none'
  anomalies: string[]
}

export interface ContractorWorkersStats {
  total: number
  contractors: number
  insurance_covered_pct: number
  special_total: number
  cert_covered_pct: number | null
  overage_count: number
  overage_warn_count: number
}

export interface ContractorWorkersPayload {
  status: ContractorWorkersStatus
  fetched_at: string | null
  message: string | null
  stats: ContractorWorkersStats | null
  workers: ContractorWorkerRow[]
}

/** 承包商在册人员副台账数据包（随域页并行一次拉回，客户端分页） */
export async function fetchContractorWorkers(): Promise<ContractorWorkersPayload> {
  return apiGet<ContractorWorkersPayload>(API_BASE_URL + '/api/v1/safety/contractor-workers')
}

// ── #4 岗位族归类（AI 归类 → 人工确认/修正 → manual 资产） ──────────

export interface ClassifyResult {
  posts_total: number
  candidates: number
  batches: number
  classified: number
  inserted: number
  updated: number
  manual_kept: number
  by_family: Record<string, number>
}

export interface OrgPostFamilyRow {
  id: string
  post_name: string
  family: string
  confidence: 'high' | 'mid' | 'low'
  note: string
  source: 'ai' | 'manual'
  updated_at: string | null
}

export interface OrgPostsFamiliesPayload {
  status: ContractorWorkersStatus
  fetched_at: string | null
  message: string | null
  posts: { post_name: string; dept_names: string[]; headcount: number }[]
  families: { family: string; headcount: number }[] | null
}

/** 岗位字典 + 族×人数聚合（#4；服务端日级缓存） */
export async function fetchOrgPostsFamilies(): Promise<OrgPostsFamiliesPayload> {
  return apiGet<OrgPostsFamiliesPayload>(
    API_BASE_URL + '/api/v1/safety/contractor-workers/org-posts',
  )
}

/** 手动触发批量归类（manual 行不覆盖） */
export async function classifyOrgPosts(): Promise<ClassifyResult> {
  return apiPost<ClassifyResult>(
    API_BASE_URL + '/api/v1/safety/contractor-workers/org-posts/classify',
  )
}

/** 归类清单（source='ai' 为待确认工作集） */
export async function fetchOrgPostFamilies(
  source?: string,
): Promise<OrgPostFamilyRow[]> {
  const qs = source ? `?source=${source}` : ''
  const data = await apiGet<{ items: OrgPostFamilyRow[]; total: number }>(
    API_BASE_URL + `/api/v1/safety/contractor-workers/org-posts/families${qs}`,
  )
  return data.items
}

/** 按 AI 归类确认（ai→manual） */
export async function confirmOrgPostFamily(id: string): Promise<OrgPostFamilyRow> {
  return apiPost<OrgPostFamilyRow>(
    API_BASE_URL + `/api/v1/safety/contractor-workers/org-posts/families/${id}/confirm`,
  )
}

/** 人工修正岗位族（改后置 manual） */
export async function updateOrgPostFamily(
  id: string,
  family: string,
  note?: string,
): Promise<OrgPostFamilyRow> {
  return apiPatch<OrgPostFamilyRow>(
    API_BASE_URL + `/api/v1/safety/contractor-workers/org-posts/families/${id}`,
    { family, note },
  )
}
