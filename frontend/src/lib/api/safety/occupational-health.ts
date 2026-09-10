import type { OhPerson, OhPersonQueryParams, OhPersonStats, OhHealthExam, OhHealthExamQueryParams, OhExamStats, OhFollowup, OhFollowupQueryParams, OhPosition, OhPositionQueryParams, OhHazardFactor, OhHazardFactorQueryParams } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 职业健康人员台账（分页） */
export async function fetchOhPersons(
  params?: OhPersonQueryParams,
): Promise<{ items: OhPerson[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.position) sp.set('position', params.position)
  if (params?.hazard_exposure) sp.set('hazard_exposure', params.hazard_exposure)
  if (params?.last_exam_conclusion) sp.set('last_exam_conclusion', params.last_exam_conclusion)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/oh/persons' + (qs ? '?' + qs : ''))
}

/** 职业健康人员统计 */
export async function fetchOhPersonStats(): Promise<OhPersonStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/oh/persons/stats')
}

/** 职业健康体检记录（分页） */
export async function fetchOhExams(
  params?: OhHealthExamQueryParams,
): Promise<{ items: OhHealthExam[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', String(params.status))
  if (params?.exam_type) sp.set('exam_type', String(params.exam_type))
  if (params?.department) sp.set('department', params.department)
  if (params?.ai_conclusion) sp.set('ai_conclusion', String(params.ai_conclusion))
  if (params?.ai_parse_status) sp.set('ai_parse_status', String(params.ai_parse_status))
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/oh-health-exams' + (qs ? '?' + qs : ''))
}

/** 职业健康体检统计 */
export async function fetchOhExamStats(): Promise<OhExamStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/oh-health-exams/stats')
}

/** 职业健康异常随访（分页） */
export async function fetchOhFollowups(
  params?: OhFollowupQueryParams,
): Promise<{ items: OhFollowup[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', String(params.status))
  if (params?.category) sp.set('category', String(params.category))
  if (params?.person_id) sp.set('person_id', params.person_id)
  if (params?.due_order !== undefined) sp.set('due_order', String(params.due_order))
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/oh/followups' + (qs ? '?' + qs : ''))
}

/** 职业健康岗位危害台账（分页） */
export async function fetchOhPositions(
  params?: OhPositionQueryParams,
): Promise<{ items: OhPosition[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.hazard_factors_status) sp.set('hazard_factors_status', String(params.hazard_factors_status))
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/oh/positions' + (qs ? '?' + qs : ''))
}

/** 职业健康危害因素 PPE 字典 */
export async function fetchOhHazardFactors(
  params?: OhHazardFactorQueryParams,
): Promise<OhHazardFactor[]> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/oh/hazard-factors' + (qs ? '?' + qs : ''))
}
