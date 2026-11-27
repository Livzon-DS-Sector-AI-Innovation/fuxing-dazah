'use server'

import { fetchHrApi } from './_helpers'
import type { ProbationReviewItem, ProbationSafetyExamItem } from '@/types/hr'

/** 转正评估列表 */
export async function fetchProbationReviews(status?: string): Promise<{ data: ProbationReviewItem[] }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return fetchHrApi(`/hr/probation-reviews${qs}`, { errorMessage: '获取转正评估失败' })
}

/** 发起转正评估：三级审批（直属上级→部门经理→分管领导），审批人自动解析 */
export async function createProbationReview(employeeId: string): Promise<{
  code: number; message: string
}> {
  return fetchHrApi('/hr/probation-reviews', {
    method: 'POST',
    body: JSON.stringify({ employee_id: employeeId }),
    errorMessage: '发起转正评估失败',
  })
}

/** HR 确认生效（兜底：源表回写失败重试 / 线下沟通完毕直接生效） */
export async function finalizeProbationReview(id: string, hrNote?: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/probation-reviews/${id}/finalize`, {
    method: 'POST',
    body: JSON.stringify({ hr_note: hrNote || null }),
    errorMessage: '确认失败',
  })
}

/** 取消进行中的评估 */
export async function cancelProbationReview(id: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/probation-reviews/${id}/cancel`, {
    method: 'POST',
    errorMessage: '取消失败',
  })
}

/** 安全考试结果列表（重点岗位 60 天节点） */
export async function fetchProbationSafetyExams(employeeId?: string): Promise<{ data: ProbationSafetyExamItem[] }> {
  const qs = employeeId ? `?employee_id=${encodeURIComponent(employeeId)}` : ''
  return fetchHrApi(`/hr/probation-safety-exams${qs}`, { errorMessage: '获取安全考试记录失败' })
}

/** 录入安全考试结果（安全办） */
export async function createProbationSafetyExam(input: {
  employee_id: string
  exam_date: string
  passed: boolean
  score?: number
  remark?: string
}): Promise<{ code: number; message: string }> {
  return fetchHrApi('/hr/probation-safety-exams', {
    method: 'POST',
    body: JSON.stringify(input),
    errorMessage: '录入安全考试结果失败',
  })
}

/** 删除安全考试记录（软删） */
export async function deleteProbationSafetyExam(id: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/probation-safety-exams/${id}`, {
    method: 'DELETE',
    errorMessage: '删除考试记录失败',
  })
}
