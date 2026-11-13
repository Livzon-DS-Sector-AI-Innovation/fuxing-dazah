'use server'

import { fetchHrApi } from './_helpers'
import type { ProbationReviewItem } from '@/types/hr'

/** 转正评估列表 */
export async function fetchProbationReviews(status?: string): Promise<{ data: ProbationReviewItem[] }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return fetchHrApi(`/hr/probation-reviews${qs}`, { errorMessage: '获取转正评估失败' })
}

/** 发起转正评估：机器人私发评估卡片给部门负责人 */
export async function createProbationReview(employeeId: string, reviewerName: string): Promise<{
  code: number; message: string
}> {
  return fetchHrApi('/hr/probation-reviews', {
    method: 'POST',
    body: JSON.stringify({ employee_id: employeeId, reviewer_name: reviewerName }),
    errorMessage: '发起转正评估失败',
  })
}

/** HR 确认生效（通过=写源表转正；延长=改到期日；不通过=仅完结） */
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
