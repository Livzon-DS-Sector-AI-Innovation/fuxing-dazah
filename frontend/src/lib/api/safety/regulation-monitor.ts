/** 法规采集监控 api client（只读，整信封单函数；三态渲染在组件侧） */

import { apiGet, API_BASE_URL } from '@/lib/http-client'
import type {
  RegulationMonitorData,
  RegulationRunDetail,
} from '@/types/safety'

/** 拉取采集监控聚合信封（源健康/最新法规/漏斗/运行历史，一次请求） */
export async function fetchRegulationMonitor(
  page = 1,
  pageSize = 20,
): Promise<RegulationMonitorData> {
  const params = new URLSearchParams()
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return apiGet(
    `${API_BASE_URL}/api/v1/safety/regulation-monitor?${params.toString()}`,
  )
}

/** 拉取运行详情（ragplus 采集段 + 本仓收录段两段拼接） */
export async function fetchRegulationRunDetail(
  runId: string,
): Promise<RegulationRunDetail> {
  return apiGet(
    `${API_BASE_URL}/api/v1/safety/regulation-monitor/runs/${encodeURIComponent(runId)}`,
  )
}
