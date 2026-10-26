/**
 * 承包商在册人员副台账（3.x 平台关联 F1）API client。
 *
 * 三态信封口径同 domain-pages：live=本次拉取成功（fetched_at=台账时点）；
 * degraded=拉取失败回退旧缓存（fetched_at=缓存时点）；empty=首次失败无缓存。
 * 行内身份证/手机已由后端打码（前 3 后 2），前端不接触明文。
 */
import { apiGet, API_BASE_URL } from '@/lib/http-client'

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
