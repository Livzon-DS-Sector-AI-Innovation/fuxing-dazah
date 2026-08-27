'use server'

import { revalidatePath } from 'next/cache'
import { fetchHrApi, fetchHrDownload } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 月度绩效考核 ───

export async function fetchPerformanceEvaluations(params?: {
  month?: string; department?: string; status?: string; page?: number; page_size?: number
}): Promise<{ code: number; data: { items: any[]; total: number; page: number; page_size: number }; message: string }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/performance-evaluations${qs}`)
}

export async function fetchMyPerformanceEvaluations(month?: string): Promise<{ code: number; data: { items: any[]; total: number }; message: string }> {
  const qs = buildQueryString(month ? { month } : {})
  return fetchHrApi(`/hr/performance-evaluations/my${qs}`)
}

export async function fetchPerformanceEvaluation(id: string): Promise<{ code: number; data: any; message: string }> {
  return fetchHrApi(`/hr/performance-evaluations/${id}`)
}

export async function createPerformanceEvaluation(payload: any): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi('/hr/performance-evaluations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  revalidatePath('/hr/performance')
  return result
}

export async function updatePerformanceEvaluation(id: string, payload: any): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi(`/hr/performance-evaluations/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  revalidatePath('/hr/performance')
  return result
}

export async function submitSelfEvaluation(id: string): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi(`/hr/performance-evaluations/${id}/submit-self`, { method: 'POST' })
  revalidatePath('/hr/performance')
  return result
}

export async function submitLeaderEvaluation(id: string): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi(`/hr/performance-evaluations/${id}/submit-leader`, { method: 'POST' })
  revalidatePath('/hr/performance')
  return result
}

export async function autoCreatePerformanceEvaluations(month: string): Promise<{ code: number; data: { created: number }; message: string }> {
  const result = await fetchHrApi(`/hr/performance-evaluations/auto-create?month=${encodeURIComponent(month)}`, { method: 'POST' })
  revalidatePath('/hr/performance')
  return result
}

// ─── 考核项目配置 ───

export async function fetchPerformanceCategories(): Promise<{ code: number; data: any[]; message: string }> {
  return fetchHrApi('/hr/performance-categories')
}

export async function createPerformanceCategory(payload: { name: string; weight: number; evaluator?: string; sort_order?: number }): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi('/hr/performance-categories', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  revalidatePath('/hr/performance')
  return result
}

export async function updatePerformanceCategory(id: string, payload: any): Promise<{ code: number; data: any; message: string }> {
  const result = await fetchHrApi(`/hr/performance-categories/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  revalidatePath('/hr/performance')
  return result
}

export async function deletePerformanceCategory(id: string): Promise<{ code: number; message: string }> {
  const result = await fetchHrApi(`/hr/performance-categories/${id}`, { method: 'DELETE' })
  revalidatePath('/hr/performance')
  return result
}

// ─── 考核项目评分 ───

export async function fetchCategoryScores(evaluationId: string): Promise<{ code: number; data: any[]; message: string }> {
  return fetchHrApi(`/hr/performance-evaluations/${evaluationId}/category-scores`)
}

export async function saveCategoryScores(evaluationId: string, scores: { evaluation_id: string; category_id: string; score: number | null; weight: number }[]): Promise<{ code: number; message: string }> {
  const result = await fetchHrApi(`/hr/performance-evaluations/${evaluationId}/category-scores`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scores }),
  })
  revalidatePath('/hr/performance')
  return result
}

// ─── 汇总报表（按项目一张表） ───

export async function fetchPerformanceReport(month: string): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(`/hr/performance-reports?month=${encodeURIComponent(month)}`)
}

// ─── 部门权重 ───

export async function fetchDeptWeights(categoryId: string): Promise<{ code: number; data: { department: string; weight: number }[]; message: string }> {
  return fetchHrApi(`/hr/performance-categories/${categoryId}/dept-weights`)
}

export async function saveDeptWeights(categoryId: string, weights: { department: string; weight: number }[]): Promise<{ code: number; message: string }> {
  const result = await fetchHrApi(`/hr/performance-categories/${categoryId}/dept-weights`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ weights }),
  })
  return result
}
