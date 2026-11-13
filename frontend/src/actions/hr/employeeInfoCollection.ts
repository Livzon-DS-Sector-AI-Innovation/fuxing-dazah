'use server'

import { fetchHrApi } from './_helpers'
import type { EmployeeInfoCollectionItem } from '@/types/hr'

/** 信息收集任务列表（含与档案现值的逐字段差异） */
export async function fetchInfoCollections(status?: string): Promise<{ data: EmployeeInfoCollectionItem[] }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return fetchHrApi(`/hr/employee-info-collections${qs}`, { errorMessage: '获取信息收集任务失败' })
}

/** 批量发起收集：机器人私发表单卡片给所选员工 */
export async function createInfoCollections(employeeIds: string[]): Promise<{
  code: number; message: string; data: { created: number; skipped: Array<{ name?: string; employee_id?: string; reason: string }> }
}> {
  return fetchHrApi('/hr/employee-info-collections', {
    method: 'POST',
    body: JSON.stringify({ employee_ids: employeeIds }),
    errorMessage: '发起信息收集失败',
  })
}

/** 采纳：写入飞书源表并预更新本地档案 */
export async function approveInfoCollection(id: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/employee-info-collections/${id}/approve`, {
    method: 'POST',
    errorMessage: '采纳失败',
  })
}

/** 驳回：记录原因并给员工重发填写卡片 */
export async function rejectInfoCollection(id: string, reason: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/employee-info-collections/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
    errorMessage: '驳回失败',
  })
}
