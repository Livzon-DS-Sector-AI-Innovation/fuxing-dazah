'use server'

import { DashboardStats } from '@/types/hr'
import { fetchHrApi } from './_helpers'

/** 获取仪表盘统计数据 */
export async function fetchDashboardStats(): Promise<DashboardStats> {
  return fetchHrApi<{ code: number; message: string; data: DashboardStats }>(
    '/hr/dashboard/stats',
    { errorMessage: '获取仪表盘数据失败' }
  ).then(r => r.data)
}
