/**
 * 四新域页面数据层（3.0 四期 1-C）。
 *
 * 三态信封（后端 service/domain_pages.py，字段口径=DESIGN 蓝本）：
 * - not_connected 未接入：registry 连接位空（表未建）是常态；
 * - live 已接入：stats/ledger 实数；
 * - degraded 降级：连接有效但读取失败（errors 标注）。
 * stats 键与 ledger 行英文字段见 docs/DESIGN-安全模块3.0四期-四新域表结构
 * 与页面口径-20261014.md 各域「统计口径/主台账」表。
 */
import { apiGet, API_BASE_URL } from '@/lib/http-client'

export type DomainPageStatus = 'not_connected' | 'live' | 'degraded'

/** 菜单/端点 key（与 menu-config safety 子项 key 一致） */
export type DomainPageKey = 'training-behavior' | 'facilities' | 'incidents'

export interface DomainLedgerMeta {
  total: number
  page: number
  page_size: number
}

/** 主台账行：record_id + 蓝本英文字段（str/list[str]/null） */
export type DomainLedgerRow = { record_id: string } & Record<string, unknown>

export interface DomainPageData {
  status: DomainPageStatus
  stats: Record<string, number | null> | null
  ledger: { data: DomainLedgerRow[]; meta: DomainLedgerMeta }
  errors: string[]
}

/** 单域页面数据（分页参数只在台账维度） */
export async function fetchDomainPage(
  domain: DomainPageKey,
  params?: { page?: number; page_size?: number },
): Promise<DomainPageData> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + `/api/v1/safety/${domain}` + (qs ? '?' + qs : ''))
}
