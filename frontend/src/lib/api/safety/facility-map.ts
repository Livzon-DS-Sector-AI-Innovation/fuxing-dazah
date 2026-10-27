/**
 * 厂区风险分区图卡（3.x 平台关联 F2）API client。
 *
 * GET /safety/facility-map/pins：当日作业票/报警按分区聚合 + 未映射清单；
 * 分区轮廓不走接口（前端静态资产 src/data/tiji-risk-districts.json）。
 * 单路数据源失败时后端降级返回（errors 非空、该路零贡献）。
 *
 * #2 AI 建议映射（人工确认门）：scan（手动批处理）/ suggestions 清单 /
 * 单条确认 / 单条忽略 / 批量确认 high。
 */
import { apiGet, apiPost, API_BASE_URL } from '@/lib/http-client'

export type PinRefKind = 'job' | 'fire' | 'central'

export interface FacilityMapPinRef {
  kind: PinRefKind
  ticket_type?: string | null
  ticket_no?: string | null
  work_site?: string | null
  work_content?: string | null
  alarm_time?: string | null
  alarm_type?: string | null
  location?: string | null
  alarm_date?: string | null
  alarm_description?: string | null
  workshop?: string | null
}

export interface FacilityMapDistrictPin {
  dist_id: string
  jobs: { hot: number; confined: number; other: number }
  alarms: { fire: number; central: number }
  refs: FacilityMapPinRef[]
  truncated: boolean
}

export interface FacilityMapUnmapped {
  text: string
  count: number
  kinds: string[]
}

export interface FacilityMapPinsPayload {
  date: string
  pins: FacilityMapDistrictPin[]
  unmapped: FacilityMapUnmapped[]
  errors: string[]
}

/** 当日分布 pins（缺省后端北京时间今日；本卡不做日期切换） */
export async function fetchFacilityMapPins(): Promise<FacilityMapPinsPayload> {
  return apiGet<FacilityMapPinsPayload>(API_BASE_URL + '/api/v1/safety/facility-map/pins')
}

// ── #2 AI 建议映射 ──────────────────────────────────────────────────

export interface DistrictSuggestionRow {
  id: string
  location_text: string
  count: number
  kinds: string[]
  dist_id: string | null
  dist_name: string | null
  confidence: 'high' | 'mid' | 'low'
  reason: string
  batch_id: string
  status: 'pending' | 'confirmed' | 'ignored'
  created_at: string | null
}

export interface SuggestionScanResult {
  days: number
  unmapped_texts: number
  candidates: number
  batches: number
  suggested: number
  no_judgement: number
  batch_id: string | null
}

/** 建议清单（缺省 pending=确认页工作集） */
export async function fetchDistrictSuggestions(
  status: string = 'pending',
): Promise<DistrictSuggestionRow[]> {
  const data = await apiGet<{ items: DistrictSuggestionRow[] }>(
    API_BASE_URL + `/api/v1/safety/facility-map/suggestions?status=${status}`,
  )
  return data.items
}

/** 手动批处理：收集近 N 天未映射 → AI 建议 → 落 pending 行 */
export async function scanDistrictSuggestions(days = 30): Promise<SuggestionScanResult> {
  return apiPost<SuggestionScanResult>(
    API_BASE_URL + '/api/v1/safety/facility-map/suggestions/scan',
    { days },
  )
}

/** 单条确认（写 location_district_map，source=ai_confirmed） */
export async function confirmDistrictSuggestion(id: string): Promise<unknown> {
  return apiPost(API_BASE_URL + `/api/v1/safety/facility-map/suggestions/${id}/confirm`)
}

/** 单条忽略（下轮收集排除） */
export async function ignoreDistrictSuggestion(id: string): Promise<unknown> {
  return apiPost(API_BASE_URL + `/api/v1/safety/facility-map/suggestions/${id}/ignore`)
}

/** 批量确认全部 high 置信建议 */
export async function confirmHighDistrictSuggestions(): Promise<{
  confirmed: number
  map_created: number
}> {
  return apiPost(API_BASE_URL + '/api/v1/safety/facility-map/suggestions/confirm-high')
}
