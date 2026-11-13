// R3 运维自愈观测 REST 封装（对齐 api/ops_selfheal.py；页面 /safety/ops-selfheal）

import { apiGet, apiPost, API_BASE_URL } from '@/lib/http-client'
import type {
  ExtendWindowResult,
  OpsSelfhealTicketList,
  OpsSelfhealTimeline,
} from '@/types/safety/ops-selfheal'

const BASE = `${API_BASE_URL}/api/v1/safety/ops-selfheal`

/** 工单列表（分页 + 阶段/信号/job 筛选） */
export async function fetchOpsSelfhealTickets(params: {
  page?: number
  page_size?: number
  stage?: string | null
  signal?: string | null
  job_name?: string | null
}): Promise<OpsSelfhealTicketList> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.stage) qs.set('stage', params.stage)
  if (params.signal) qs.set('signal', params.signal)
  if (params.job_name) qs.set('job_name', params.job_name)
  return apiGet(`${BASE}/tickets?${qs.toString()}`)
}

/** 工单全时间线回放 */
export async function fetchOpsSelfhealTimeline(
  ticketId: string,
): Promise<OpsSelfhealTimeline> {
  return apiGet(`${BASE}/tickets/${ticketId}/timeline`)
}

/** 失败重试（重投 system input） */
export async function retryOpsSelfhealTicket(
  ticketId: string,
): Promise<{ id: string; queued: boolean; note?: string }> {
  return apiPost(`${BASE}/tickets/${ticketId}/retry`)
}

/** L2 一键执行：延长当日补发窗口 */
export async function extendOpsSelfhealWindow(
  ticketId: string,
  args?: { until_hour?: number; until_minute?: number },
): Promise<ExtendWindowResult> {
  return apiPost(`${BASE}/tickets/${ticketId}/extend-window`, args ? { args } : undefined)
}
