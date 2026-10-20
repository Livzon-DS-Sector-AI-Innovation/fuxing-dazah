/**
 * 安全设备设施管理数据层（facilities-p1）。
 *
 * 三台账三态信封（backend facilities/page.py）：not_connected=连接位留空
 * （一期常态）；live=直读出数；degraded=读取降级。任务中心接口随票 03 补齐。
 */
import { apiGet, apiPost, API_BASE_URL } from '@/lib/http-client'
import type {
  FacilitiesLedgerKey,
  FacilitiesLedgerPageData,
  FacilityTask,
  FacilityTaskDetail,
  FacilityTaskSummary,
} from '@/types/safety/facilities'

export async function fetchFacilitiesLedger(
  ledger: FacilitiesLedgerKey,
  params?: { page?: number; page_size?: number },
): Promise<FacilitiesLedgerPageData> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + `/api/v1/safety/facilities/ledgers/${ledger}` + (qs ? '?' + qs : ''))
}

export async function fetchFacilityTasks(params?: {
  status?: string
  department?: string
  biz_type?: string
  group_key?: string
  overdue?: boolean
  page?: number
  page_size?: number
}): Promise<{ items: FacilityTask[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.status) sp.set('status', params.status)
  if (params?.department) sp.set('department', params.department)
  if (params?.biz_type) sp.set('biz_type', params.biz_type)
  if (params?.group_key) sp.set('group_key', params.group_key)
  if (params?.overdue) sp.set('overdue', 'true')
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/facility-tasks' + (qs ? '?' + qs : ''))
}

export async function fetchFacilityTaskSummary(): Promise<FacilityTaskSummary> {
  return apiGet(API_BASE_URL + '/api/v1/safety/facility-tasks/summary')
}

export async function fetchFacilityTaskDetail(id: string): Promise<FacilityTaskDetail> {
  return apiGet(API_BASE_URL + `/api/v1/safety/facility-tasks/${id}`)
}

/** 管理员干预：误关恢复（closed/cancelled → issued；原因可选） */
export async function reopenFacilityTask(id: string, reason?: string) {
  return apiPost(API_BASE_URL + `/api/v1/safety/facility-tasks/${id}/reopen`, {
    reason: reason || null,
  })
}

/** 管理员干预：取消（原因必填） */
export async function cancelFacilityTask(id: string, reason: string) {
  return apiPost(API_BASE_URL + `/api/v1/safety/facility-tasks/${id}/cancel`, { reason })
}
