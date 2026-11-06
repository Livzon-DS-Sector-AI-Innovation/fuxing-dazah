import type { HazardQualityDashboard } from '@/types/safety'
import { apiGet, API_BASE_URL } from '@/lib/http-client'

/** 隐患 AI 识别质量看板（实时聚合；指标与离线 replay 同口径） */
export async function fetchHazardQualityDashboard(
  days: 7 | 30 = 30,
): Promise<HazardQualityDashboard> {
  return apiGet(
    `${API_BASE_URL}/api/v1/safety/hazard-quality/dashboard?days=${days}`,
  )
}
