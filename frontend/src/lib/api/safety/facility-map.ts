/**
 * 厂区风险分区图卡（3.x 平台关联 F2）API client。
 *
 * GET /safety/facility-map/pins：当日作业票/报警按分区聚合 + 未映射清单；
 * 分区轮廓不走接口（前端静态资产 src/data/tiji-risk-districts.json）。
 * 单路数据源失败时后端降级返回（errors 非空、该路零贡献）。
 */
import { apiGet, API_BASE_URL } from '@/lib/http-client'

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
