import type { SafetyTraining, SafetyTrainingQueryParams, TrainingRecord } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 安全培训列表（分页） */
export async function fetchTrainings(
  params?: SafetyTrainingQueryParams,
): Promise<{ items: SafetyTraining[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.training_type) sp.set('training_type', params.training_type)
  if (params?.department) sp.set('department', params.department)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/trainings' + (qs ? '?' + qs : ''))
}

/** 某培训的记录列表 */
export async function fetchTrainingRecords(trainingId: string): Promise<TrainingRecord[]> {
  return apiGet(API_BASE_URL + '/api/v1/safety/trainings/' + trainingId + '/records')
}

/** 证书列表（分页） */
export async function fetchTrainingCertificates(
  params: { page?: number; page_size?: number; certificate_status?: string; keyword?: string } = {},
): Promise<{ items: TrainingRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  if (params.certificate_status) sp.set('certificate_status', params.certificate_status)
  if (params.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/training-certificates' + (qs ? '?' + qs : ''))
}
