'use server'

import { revalidatePath } from 'next/cache'
import {
  CandidateCreateInput,
  CandidateUpdateInput,
  CandidateStatusTransition,
  JobRequirementCreateInput,
  JobRequirementUpdateInput,
  InterviewCreateInput,
  InterviewUpdateInput,
} from '@/types/hr'
import { fetchHrApi, fetchHrText, fetchHrDownload } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 简历解析 ───

export async function parseResumeAction(formData: FormData) {
  return fetchHrApi('/hr/candidates/parse-resume', {
    method: 'POST',
    body: formData,
    errorMessage: '简历解析失败',
  })
}

export async function updateCandidateAction(id: string, data: Record<string, unknown>): Promise<void> {
  await fetchHrApi(`/hr/candidates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新失败',
  })
}

export async function deleteCandidateAction(id: string): Promise<void> {
  await fetchHrApi(`/hr/candidates/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

export async function updateCandidateRecommendationLevelAction(id: string, level: string): Promise<void> {
  await fetchHrApi(`/hr/candidates/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ recommendation_level: level }),
    errorMessage: '更新失败',
  })
}

// ─── 岗位需求 ───

export async function fetchJobRequirements(params?: { status?: string }): Promise<{ data: any[] }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/job-requirements${qs}`, { errorMessage: '获取岗位需求失败' })
}

export async function createJobRequirement(data: JobRequirementCreateInput) {
  const res = await fetchHrApi('/hr/job-requirements', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建岗位需求失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function updateJobRequirement(id: string, data: JobRequirementUpdateInput) {
  const res = await fetchHrApi(`/hr/job-requirements/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新岗位需求失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function deleteJobRequirement(id: string) {
  const res = await fetchHrApi(`/hr/job-requirements/${id}`, {
    method: 'DELETE',
    errorMessage: '删除岗位需求失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

// ─── 候选人 ───

export async function fetchCandidates(params: Record<string, unknown> = {}): Promise<{ data: any[]; meta?: { total: number } }> {
  const qs = buildQueryString({
    job_requirement_id: params.job_requirement_id,
    status: params.status,
    keyword: params.keyword,
    candidate_type: params.candidate_type,
    page: params.page || 1,
    page_size: params.page_size || 100,
  })
  return fetchHrApi(`/hr/candidates${qs}`, { errorMessage: '获取候选人列表失败' })
}

/** 批量导入候选人（Excel 上传） */
export async function uploadCandidates(formData: FormData): Promise<{
  code: number; message: string; data: { created: number; updated: number; errors?: string[] }
}> {
  return fetchHrApi('/hr/candidates/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

/** 下载候选人导入模板 */
export async function downloadCandidateTemplate(): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/candidates/template', {
    errorMessage: '下载模板失败',
  })
  return { base64, filename: filename || 'candidate_import_template.xlsx' }
}

export async function fetchCandidateById(id: string): Promise<{ code: number; message: string; data: unknown }> {
  return fetchHrApi(`/hr/candidates/${id}`, { errorMessage: '获取候选人失败' })
}

/** 简历预览（PDF），客户端用 base64ToObjectUrl 转 blob URL 后嵌入 iframe */
export async function fetchResumePreview(candidateId: string): Promise<{ base64: string; filename: string | null }> {
  return fetchHrDownload(`/hr/candidates/${candidateId}/resume-preview`, { errorMessage: '简历加载失败' })
}

export async function createCandidate(data: CandidateCreateInput) {
  const res = await fetchHrApi('/hr/candidates', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建候选人失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function updateCandidate(id: string, data: CandidateUpdateInput) {
  const res = await fetchHrApi(`/hr/candidates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新候选人失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function deleteCandidate(id: string) {
  const res = await fetchHrApi(`/hr/candidates/${id}`, {
    method: 'DELETE',
    errorMessage: '删除候选人失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function transitionCandidateStatus(id: string, data: CandidateStatusTransition) {
  const res = await fetchHrApi(`/hr/candidates/${id}/status`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '状态流转失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

/** 候选人一键入职 */
export async function onboardCandidate(candidateId: string): Promise<{ code: number; message: string; data?: { employee_number?: string } }> {
  return fetchHrApi(`/hr/candidates/${candidateId}/onboard`, {
    method: 'POST',
    errorMessage: '入职失败',
  })
}

// ─── 面试管理 ───

export async function fetchCandidateInterviews(candidateId: string): Promise<{ data: any[] }> {
  return fetchHrApi(`/hr/candidates/${candidateId}/interviews`, { errorMessage: '获取面试列表失败' })
}

export async function fetchInterviewEvaluation(interviewId: string): Promise<{ data: any }> {
  return fetchHrApi(`/hr/interviews/${interviewId}/evaluation`, { errorMessage: '获取AI评估结果失败' })
}

export async function createInterview(data: InterviewCreateInput) {
  const res = await fetchHrApi('/hr/interviews', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '安排面试失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function updateInterview(id: string, data: InterviewUpdateInput) {
  const res = await fetchHrApi(`/hr/interviews/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新面试失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function deleteInterview(id: string) {
  const res = await fetchHrApi(`/hr/interviews/${id}`, {
    method: 'DELETE',
    errorMessage: '取消面试失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

// ─── AI评估 ───

export async function evaluateInterview(id: string) {
  const res = await fetchHrApi(`/hr/interviews/${id}/evaluate`, {
    method: 'POST',
    errorMessage: 'AI评估失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

// ─── Offer ───

export async function sendOfferAction(candidateId: string, formData: FormData) {
  const res = await fetchHrApi(`/hr/candidates/${candidateId}/send-offer`, {
    method: 'POST',
    body: formData,
    errorMessage: '发送Offer失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

/** 预览 Offer（返回 HTML 文本） */
export async function previewOffer(candidateId: string, formData: FormData): Promise<string> {
  return fetchHrText(`/hr/candidates/${candidateId}/preview-offer`, {
    method: 'POST',
    body: formData,
    errorMessage: '预览失败',
  })
}

// ─── 审核 ───

export async function fetchPendingReviews(reviewer?: string): Promise<{ data: any[] }> {
  const qs = buildQueryString({ reviewer })
  return fetchHrApi(`/hr/candidates/pending-review${qs}`, { errorMessage: '获取待审核列表失败' })
}

export async function fetchCandidateComparison(jobRequirementId: string): Promise<{ data: unknown[] }> {
  return fetchHrApi(`/hr/job-requirements/${jobRequirementId}/candidates/comparison`, { errorMessage: '获取对比数据失败' })
}

export async function fetchRecruitmentStats(): Promise<{ data: import('@/types/hr').RecruitmentStats }> {
  return fetchHrApi('/hr/recruitment/stats', { errorMessage: '获取统计数据失败' })
}

export async function pushOnboardingReview(candidateId: string, data: { pushed_by: string; push_note?: string }) {
  const res = await fetchHrApi(`/hr/candidates/${candidateId}/push-onboarding-review`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '发起入职审批失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function fetchOnboardingTasks(candidateId: string): Promise<{ data: import('@/types/hr').OnboardingTask[] }> {
  return fetchHrApi(`/hr/candidates/${candidateId}/onboarding-tasks`, { errorMessage: '获取入职任务失败' })
}

export async function updateOnboardingTask(candidateId: string, taskId: string, data: Record<string, unknown>): Promise<{ data: import('@/types/hr').OnboardingTask }> {
  return fetchHrApi(`/hr/candidates/${candidateId}/onboarding-tasks/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新任务失败',
  })
}

export async function pushCandidateReview(candidateId: string, data: { pushed_by: string; push_note?: string; reviewer?: string }) {
  const res = await fetchHrApi(`/hr/candidates/${candidateId}/push-review`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '推送审核失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}

export async function decideCandidateReview(candidateId: string, data: { review_id?: string; decision: string; review_comment?: string }) {
  const res = await fetchHrApi(`/hr/candidates/${candidateId}/decide-review`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '审核操作失败',
  })
  revalidatePath('/hr/recruitment')
  return res
}


// ─── 候选人胜任度多维分析报告 ───

export async function fetchCandidateAnalysisReports(candidateId: string): Promise<{
  code: number
  message: string
  data: any[]
}> {
  return fetchHrApi(`/hr/candidates/${candidateId}/analysis-reports`, { errorMessage: '获取分析报告失败' })
}

export async function generateCandidateAnalysisReport(candidateId: string, interviewId: string) {
  return fetchHrApi(`/hr/candidates/${candidateId}/analysis-reports`, {
    method: 'POST',
    body: JSON.stringify({ interview_id: interviewId }),
    errorMessage: '生成分析报告失败',
  })
}
