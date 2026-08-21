'use server'

import { revalidatePath } from 'next/cache'
import type {
  TitleReviewActivity,
  TitleReviewActivityCreateInput,
  TitleReviewActivityListItem,
  TitleReviewActivityUpdateInput,
  TitleReviewApplication,
  TitleReviewDeptCommittee,
  TitleReviewDeptCommitteeInput,
  TitleReviewJudge,
  TitleReviewJudgeAssignItem,
  TitleReviewReconcileStats,
  TitleReviewResultRow,
} from '@/types/hr'
import { fetchHrApi } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 活动 ───

export async function fetchTitleActivities(params?: {
  status?: string
  keyword?: string
  page?: number
  page_size?: number
}): Promise<{ code: number; message: string; data: TitleReviewActivityListItem[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 100 })
  return fetchHrApi(`/hr/title/activities${qs}`, { errorMessage: '获取评定活动列表失败' })
}

export async function fetchTitleActivity(id: string): Promise<{ code: number; message: string; data: TitleReviewActivity & { dimensions: any[] } }> {
  return fetchHrApi(`/hr/title/activities/${id}`, { errorMessage: '获取活动详情失败' })
}

export async function createTitleActivity(data: TitleReviewActivityCreateInput) {
  const res = await fetchHrApi(`/hr/title/activities`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建活动失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function updateTitleActivity(id: string, data: TitleReviewActivityUpdateInput) {
  const res = await fetchHrApi(`/hr/title/activities/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新活动失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function deleteTitleActivity(id: string) {
  const res = await fetchHrApi(`/hr/title/activities/${id}`, { method: 'DELETE', errorMessage: '删除活动失败' })
  revalidatePath('/hr/title-review')
  return res
}

export async function bindTitleTables(id: string) {
  const res = await fetchHrApi(`/hr/title/activities/${id}/bind-tables`, {
    method: 'POST',
    errorMessage: '绑定飞书表格失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function openTitleActivity(id: string) {
  const res = await fetchHrApi(`/hr/title/activities/${id}/open`, { method: 'POST', errorMessage: '开启申报失败' })
  revalidatePath('/hr/title-review')
  return res
}

export async function startTitleReview(id: string) {
  const res = await fetchHrApi(`/hr/title/activities/${id}/review`, { method: 'POST', errorMessage: '开启评审失败' })
  revalidatePath('/hr/title-review')
  return res
}

export async function closeTitleActivity(id: string) {
  const res = await fetchHrApi(`/hr/title/activities/${id}/close`, { method: 'POST', errorMessage: '结束活动失败' })
  revalidatePath('/hr/title-review')
  return res
}

export async function reconcileTitleActivity(id: string) {
  const res = await fetchHrApi<{ code: number; message: string; data: TitleReviewReconcileStats }>(
    `/hr/title/activities/${id}/reconcile`,
    { method: 'POST', errorMessage: '对账失败' }
  )
  revalidatePath('/hr/title-review')
  return res
}

// ─── 部门评审组 ───

export async function fetchTitleDepartments(): Promise<{ code: number; message: string; data: string[] }> {
  return fetchHrApi(`/hr/title/departments`, { errorMessage: '获取部门列表失败' })
}

export async function fetchTitleCommittees(): Promise<{ code: number; message: string; data: TitleReviewDeptCommittee[] }> {
  return fetchHrApi(`/hr/title/committees`, { errorMessage: '获取部门评审组失败' })
}

export async function saveTitleCommittee(data: TitleReviewDeptCommitteeInput) {
  const res = await fetchHrApi(`/hr/title/committees`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '保存部门评审组失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function deleteTitleCommittee(id: string) {
  const res = await fetchHrApi(`/hr/title/committees/${id}`, { method: 'DELETE', errorMessage: '删除失败' })
  revalidatePath('/hr/title-review')
  return res
}

// ─── 申报 ───

export async function fetchTitleApplications(
  activityId: string,
  params?: { status?: string; keyword?: string; page?: number; page_size?: number }
): Promise<{ code: number; message: string; data: TitleReviewApplication[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi(`/hr/title/activities/${activityId}/applications${qs}`, { errorMessage: '获取申报列表失败' })
}

export async function fetchTitleApplication(id: string): Promise<{
  code: number
  message: string
  data: TitleReviewApplication & { judges: TitleReviewJudge[] }
}> {
  return fetchHrApi(`/hr/title/applications/${id}`, { errorMessage: '获取申报详情失败' })
}

export async function fetchTitleDefaultJudges(applicationId: string): Promise<{
  code: number
  message: string
  data: { employee_id: string; name: string; employee_no?: string }[]
}> {
  return fetchHrApi(`/hr/title/applications/${applicationId}/default-judges`, { errorMessage: '获取默认评委失败' })
}

export async function assignTitleJudges(applicationId: string, judges: TitleReviewJudgeAssignItem[]) {
  const res = await fetchHrApi(`/hr/title/applications/${applicationId}/judges`, {
    method: 'POST',
    body: JSON.stringify({ judges }),
    errorMessage: '指定评委失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function finalizeTitleVotes(applicationId: string) {
  const res = await fetchHrApi(`/hr/title/applications/${applicationId}/finalize`, {
    method: 'POST',
    errorMessage: '判定失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

export async function invalidateTitleApplication(applicationId: string) {
  const res = await fetchHrApi(`/hr/title/applications/${applicationId}/invalidate`, {
    method: 'PUT',
    errorMessage: '标记失败',
  })
  revalidatePath('/hr/title-review')
  return res
}

// ─── 评委投票（内网） ───

export async function fetchMyJudgeTasks(): Promise<{
  code: number
  message: string
  data: any[]
}> {
  return fetchHrApi(`/hr/title/my-judge-tasks`, { errorMessage: '获取我的投票任务失败' })
}

export async function submitJudgeVote(
  judgeId: string,
  data: { vote_result: string; comprehensive_grade?: string; dimension_grades: Record<string, string>; review_comment?: string }
) {
  const res = await fetchHrApi(`/hr/title/judge-tasks/${judgeId}/vote`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '提交投票失败',
  })
  revalidatePath('/hr/title-judge')
  return res
}

// ─── 评审结果 ───

export async function fetchTitleResults(activityId: string): Promise<{
  code: number
  message: string
  data: TitleReviewResultRow[]
}> {
  return fetchHrApi(`/hr/title/activities/${activityId}/results`, { errorMessage: '获取评审结果失败' })
}
