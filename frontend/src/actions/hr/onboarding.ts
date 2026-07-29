'use server'

import { revalidatePath } from 'next/cache'
import {
  OnboardingRecordListResponse,
  DepartureRecordListResponse,
  OnboardingEvaluationData,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload, fetchHrText } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 入职记录 ───

export async function fetchOnboardingRecords(
  params?: {
    employee_id?: string
    department?: string
    position?: string
    is_employed?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<OnboardingRecordListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi<OnboardingRecordListResponse>(`/hr/onboarding-records${qs}`, { errorMessage: '获取入职记录失败' })
}

export async function deleteOnboardingRecord(id: string) {
  return fetchHrApi(`/hr/onboarding-records/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

// ─── 离职记录 ───

export async function fetchDepartureRecords(
  params?: {
    department?: string
    offboarding_type?: string
    keyword?: string
    sort_by?: string
    sort_order?: string
    page?: number
    page_size?: number
  }
): Promise<DepartureRecordListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi<DepartureRecordListResponse>(`/hr/departure-records${qs}`, { errorMessage: '获取离职台账记录失败' })
}

export async function createDepartureRecord(data: {
  name: string
  department: string
  position?: string
  offboarding_date?: string
  offboarding_type?: string
  reason?: string
}) {
  return fetchHrApi('/hr/departure-records', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建失败',
  })
}

export async function deleteDepartureRecordAction(id: string) {
  const res = await fetchHrApi(`/hr/departure-records/${id}`, {
    method: 'DELETE',
    errorMessage: '删除离职记录失败',
  })
  revalidatePath('/hr/departure')
  return res
}

/** 预览离职证明（返回 HTML 文本） */
export async function previewDepartureCertificate(id: string): Promise<string> {
  return fetchHrText(`/hr/departure-records/${id}/preview-certificate`, {
    method: 'POST',
    errorMessage: '预览失败',
  })
}

/** 发送离职证明邮件 */
export async function sendDepartureCertificate(id: string, formData: FormData) {
  return fetchHrApi(`/hr/departure-records/${id}/send-certificate`, {
    method: 'POST',
    body: formData,
    errorMessage: '发送失败',
  })
}

// ─── 入职/离职审批 ───

export async function fetchOnboardingApplications(): Promise<{ data: unknown[] }> {
  return fetchHrApi('/hr/onboarding-applications', { errorMessage: '获取入职申请失败' })
}

export async function fetchOffboardingApplications(): Promise<{ data: unknown[] }> {
  return fetchHrApi('/hr/offboarding-applications', { errorMessage: '获取离职申请失败' })
}

export async function approveApplication(type: 'onboarding' | 'offboarding', appId: string, status: string) {
  return fetchHrApi(`/hr/${type}-applications/${appId}/approve`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
    errorMessage: '操作失败',
  })
}

// ─── 入职台账导出（下载类，返回 base64 由客户端落地） ───

/** 7.3 新员工入职培训记录（docx） */
export async function fetchOnboardingTrainingRecord(
  employeeId: string,
  employeeName: string
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/employees/${employeeId}/onboarding-training-record`, {
    errorMessage: '生成培训记录失败',
  })
  return { base64, filename: filename || `7.3新员工入职培训记录_${employeeName}.docx` }
}

/** 7.4 岗前培训计划（xlsx） */
export async function fetchPrejobTrainingPlan(
  employeeId: string,
  employeeName: string
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/employees/${employeeId}/prejob-training-plan`, {
    errorMessage: '生成岗前培训计划失败',
  })
  return { base64, filename: filename || `7.4岗前培训计划_${employeeName}.xlsx` }
}

/** 7.12 员工上岗评估表（xlsx） */
export async function generateOnboardingEvaluation(
  data: OnboardingEvaluationData
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/onboarding-evaluation', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '生成员工上岗评估表失败',
  })
  const safeDate = data.approval_date || 'nodate'
  return { base64, filename: filename || `7.12员工上岗评估表_${safeDate}.xlsx` }
}

// ─── 岗前培训文档（POST 带培训明细，返回 docx） ───

type PrejobTrainingItem = {
  sop_number: string
  file_name: string
  content: string
  method: string
  trainer: string
  plan_date: string
}

/** 岗前培训计划（docx，含自选培训内容） */
export async function downloadPrejobTrainingPlan(
  employeeId: string,
  employeeName: string,
  trainingItems: PrejobTrainingItem[]
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/employees/${employeeId}/prejob-training-plan`, {
    method: 'POST',
    body: JSON.stringify({ training_items: trainingItems }),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `岗前培训计划_${employeeName || 'employee'}.docx` }
}

/** 培训记录（docx，含自选培训内容） */
export async function downloadEmployeeTrainingRecord(
  employeeNumber: string,
  employeeName: string,
  trainingItems: PrejobTrainingItem[]
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/employees/${employeeNumber}/training-record`, {
    method: 'POST',
    body: JSON.stringify({ training_items: trainingItems }),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `培训记录_${employeeName}.docx` }
}

/** 上岗证（docx，含自选培训内容） */
export async function downloadWorkPermit(
  employeeNumber: string,
  employeeName: string,
  trainingItems: PrejobTrainingItem[]
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/employees/${employeeNumber}/work-permit`, {
    method: 'POST',
    body: JSON.stringify({ training_items: trainingItems }),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `上岗证_${employeeName}.docx` }
}

// ─── 资料打印 ───

export async function downloadRoster(department?: string): Promise<{ base64: string; filename: string }> {
  const qs = buildQueryString({ department })
  const { base64, filename } = await fetchHrDownload(`/hr/roster${qs}`)
  return { base64, filename: filename || `花名册_${department || '全部'}.docx` }
}

export async function downloadTrainingRegistration(department?: string): Promise<{ base64: string; filename: string }> {
  const qs = buildQueryString({ department })
  const { base64, filename } = await fetchHrDownload(`/hr/training-registration${qs}`)
  return { base64, filename: filename || `个人培训登记表_${department || '全部'}.docx` }
}
