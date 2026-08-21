'use server'

import { revalidatePath } from 'next/cache'
import {
  TrainingLedgerListResponse,
  TrainingLedgerRecord,
  TrainingLedgerCreateInput,
  TrainingLedgerUpdateInput,
  TrainingLedgerPageRecord,
  AnnualTrainingPlanListResponse,
  AnnualTrainingPlan,
  AnnualTrainingPlanItem,
  AnnualTrainingPlanCreateInput,
  AnnualTrainingPlanItemBatchUpdateInput,
  TrainingSignInSheetData,
  TrainingNotificationData,
  SopTrainingRecord,
  SopTrainingEntry,
  SopTrainingPersonnel,
  SopClassificationOption,
  SopPersonnelOption,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 培训台账 ───

export async function fetchTrainingLedgers(
  params?: {
    employee_number?: string
    date_from?: string
    date_to?: string
    page?: number
    page_size?: number
  }
): Promise<TrainingLedgerListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 100 })
  return fetchHrApi<TrainingLedgerListResponse>(`/hr/training-ledgers${qs}`, { errorMessage: '获取培训台账列表失败' })
}

export async function createTrainingLedger(
  data: TrainingLedgerCreateInput
): Promise<{ code: number; message: string; data: TrainingLedgerRecord }> {
  return fetchHrApi('/hr/training-ledgers', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建培训台账记录失败',
  })
}

export async function updateTrainingLedger(
  id: string,
  data: TrainingLedgerUpdateInput
): Promise<{ code: number; message: string; data: TrainingLedgerRecord }> {
  return fetchHrApi(`/hr/training-ledgers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新培训台账记录失败',
  })
}

export async function deleteTrainingLedger(
  id: string
): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/training-ledgers/${id}`, {
    method: 'DELETE',
    errorMessage: '删除培训台账记录失败',
  })
}

// ─── 培训台账页面 ───

export async function fetchTrainingLedgerPages(): Promise<{
  code: number
  message: string
  data: TrainingLedgerPageRecord[]
}> {
  return fetchHrApi('/hr/training-ledgers/pages', { errorMessage: '获取培训台账页面列表失败' })
}

export async function createTrainingLedgerPage(
  data: { employee_number: string; employee_name: string }
): Promise<{ code: number; message: string; data: TrainingLedgerPageRecord }> {
  return fetchHrApi('/hr/training-ledgers/pages', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建培训台账页面失败',
  })
}

/** 导出个人培训台账（xlsx） */
export async function exportTrainingLedger(employeeNumber: string): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(
    `/hr/training-ledgers/export?employee_number=${encodeURIComponent(employeeNumber)}`,
    { errorMessage: '导出培训台账失败' }
  )
  return { base64, filename: filename || '培训台账.xlsx' }
}

// ─── 管理员台账 ───

export async function fetchTrainingLedgersAdmin(params?: {
  department?: string
  training_subject?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}): Promise<{ code: number; message: string; data: any[]; meta: { page: number; page_size: number; total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi(`/hr/training-ledgers/admin${qs}`, { errorMessage: '获取管理员台账列表失败' })
}

export async function batchUpdateScores(data: { records: { id: string; assessment_result: string }[] }): Promise<{ code: number; message: string; data: { updated: number } }> {
  return fetchHrApi('/hr/training-ledgers/batch-scores', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '批量更新成绩失败',
  })
}

export async function fetchTrainingLedgerStats(params?: {
  department?: string
  training_subject?: string
  date_from?: string
  date_to?: string
}): Promise<{ code: number; message: string; data: { total_count: number; assessed_count: number; qualified_count: number; unqualified_count: number; pass_rate: string; avg_score: number | null } }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/training-ledgers/admin/stats${qs}`, { errorMessage: '获取培训统计失败' })
}

export async function fetchLedgerDepartments(): Promise<{ code: number; message: string; data: string[] }> {
  return fetchHrApi('/hr/training-ledgers/admin/departments', { errorMessage: '获取台账部门列表失败' })
}

export async function fetchLedgerSubjects(department?: string): Promise<{ code: number; message: string; data: string[] }> {
  const qs = buildQueryString({ department })
  return fetchHrApi(`/hr/training-ledgers/admin/subjects${qs}`, { errorMessage: '获取培训内容列表失败' })
}

// ─── 培训文档生成（下载类） ───

/** 获取部门品种列表（去重） */
export async function fetchEmployeeVarieties(department: string): Promise<{ code: number; message: string; data: string[] }> {
  return fetchHrApi(`/hr/employee-varieties?department=${encodeURIComponent(department)}`, { errorMessage: '获取品种列表失败' })
}

/** 生成培训签到表（docx） */
export async function generateTrainingSignInSheet(
  data: TrainingSignInSheetData
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/training-sign-in-sheet', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '生成培训签到表失败',
  })
  return { base64, filename: filename || `培训签到表_${data.training_date}.docx` }
}

/** 生成培训通知（docx） */
export async function generateTrainingNotification(
  data: TrainingNotificationData
): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/training-notification', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '生成培训通知失败',
  })
  return { base64, filename: filename || `培训通知_${data.training_date}.docx` }
}

/** 导出问答实操记录表（docx，FormData 转发） */
export async function exportQaRecord(params: {
  training_content: string
  training_purpose?: string
  training_date: string
  training_method: string
  training_department: string
  questions: { file_no: string; question: string; answer: string; score: number }[]
  trainee_names: string[]
}): Promise<{ base64: string; filename: string }> {
  const fd = new FormData()
  fd.append('training_content', params.training_content)
  fd.append('training_purpose', params.training_purpose || '')
  fd.append('training_date', params.training_date)
  fd.append('training_method', params.training_method)
  fd.append('training_department', params.training_department)
  fd.append('questions_json', JSON.stringify(params.questions))
  fd.append('trainee_names_json', JSON.stringify(params.trainee_names))
  const { base64, filename } = await fetchHrDownload('/hr/training-notification/export-qa-record', {
    method: 'POST',
    body: fd,
    errorMessage: '导出问答记录表失败',
  })
  return { base64, filename: filename || `问答实操记录表_${params.training_date}.docx` }
}

/** 导出培训效果评估表（docx，FormData 转发） */
export async function exportTrainingEvaluationReport(params: {
  department: string
  training_subject: string
  training_date?: string
  training_method?: string
  trainer_name?: string
  assessment_method?: string
  expected_count?: number
  actual_count?: number
  exam_count?: number
  excellent_count?: number
  qualified_count?: number
  unqualified_count?: number
}): Promise<{ base64: string; filename: string }> {
  const fd = new FormData()
  fd.append('department', params.department)
  fd.append('training_subject', params.training_subject)
  if (params.training_date) fd.append('training_date', params.training_date)
  if (params.training_method) fd.append('training_method', params.training_method)
  if (params.trainer_name) fd.append('trainer_name', params.trainer_name)
  if (params.assessment_method) fd.append('assessment_method', params.assessment_method)
  if (params.expected_count != null) fd.append('expected_count', String(params.expected_count))
  if (params.actual_count != null) fd.append('actual_count', String(params.actual_count))
  if (params.exam_count != null) fd.append('exam_count', String(params.exam_count))
  if (params.excellent_count != null) fd.append('excellent_count', String(params.excellent_count))
  if (params.qualified_count != null) fd.append('qualified_count', String(params.qualified_count))
  if (params.unqualified_count != null) fd.append('unqualified_count', String(params.unqualified_count))
  const { base64, filename } = await fetchHrDownload('/hr/training-evaluations/export-admin', {
    method: 'POST',
    body: fd,
    errorMessage: '导出评估表失败',
  })
  return { base64, filename: filename || `培训效果评估表_${params.department}.docx` }
}

/** 同步评估补录表（FormData 转发；失败由调用方降级提示） */
export async function upsertTrainingEvaluation(data: {
  training_content: string
  department: string
  expected_count: number
  training_method?: string
  trainer_name?: string
  assessment_method?: string
}) {
  const fd = new FormData()
  fd.append('training_content', data.training_content)
  fd.append('department', data.department)
  fd.append('expected_count', String(data.expected_count))
  fd.append('training_method', data.training_method || '')
  fd.append('trainer_name', data.trainer_name || '')
  fd.append('assessment_method', data.assessment_method || '')
  return fetchHrApi('/hr/training-evaluations/upsert', {
    method: 'POST',
    body: fd,
    errorMessage: '评估补录同步失败',
  })
}

/** AI 生成考核内容（上传培训材料，FormData 转发） */
export async function generateAssessmentQuestions(formData: FormData): Promise<{ data: unknown }> {
  return fetchHrApi('/hr/training-notification/generate-assessment', {
    method: 'POST',
    body: formData,
    errorMessage: '生成失败',
  })
}

/** 导出成绩单（docx，含错题得分） */
export async function exportScoreReport(data: {
  training_content: string
  training_date: string
  training_department: string
  scores_json: string
}): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/training-notification/export-score-report', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `成绩单_${data.training_date || 'export'}.docx` }
}

/** 导出问答实操记录表（docx，含错题） */
export async function exportQaRecordWithScores(data: {
  training_content: string
  training_date: string
  training_method: string
  training_department: string
  questions_json: string
  trainee_names_json: string
  scores_json: string
}): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/training-notification/export-qa-record-with-scores', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `问答实操记录表_${data.training_date || 'export'}.docx` }
}

/** 导出考核成绩单（docx） */
export async function exportTrainingAssessmentScores(data: {
  training_content: string
  training_date: string
  department: string
  scores: { name: string; department: string; score: number }[]
}): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/training-assessment-scores/export', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || `考核成绩单_${data.training_content || 'training'}.docx` }
}

// ─── 年度培训计划 ───

export async function fetchAnnualTrainingPlans(
  params?: {
    year?: number
    department?: string
    page?: number
    page_size?: number
  }
): Promise<AnnualTrainingPlanListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 100 })
  return fetchHrApi<AnnualTrainingPlanListResponse>(`/hr/annual-training-plans${qs}`, { errorMessage: '获取年度培训计划列表失败' })
}

export async function fetchAnnualTrainingPlanById(id: string): Promise<{ code: number; message: string; data: AnnualTrainingPlan }> {
  return fetchHrApi(`/hr/annual-training-plans/${id}`, { errorMessage: '获取年度培训计划详情失败' })
}

export async function fetchPlanItems(id: string): Promise<{ code: number; message: string; data: AnnualTrainingPlanItem[] }> {
  return fetchHrApi(`/hr/annual-training-plans/${id}/items`, { errorMessage: '获取年度计划明细失败' })
}

export async function createAnnualTrainingPlan(data: AnnualTrainingPlanCreateInput) {
  const res = await fetchHrApi('/hr/annual-training-plans', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建年度培训计划失败',
  })
  revalidatePath('/hr/training/annual-plan')
  return res
}

export async function deleteAnnualTrainingPlan(id: string) {
  const res = await fetchHrApi(`/hr/annual-training-plans/${id}`, {
    method: 'DELETE',
    errorMessage: '删除年度培训计划失败',
  })
  revalidatePath('/hr/training/annual-plan')
  return res
}

export async function batchUpdatePlanItems(id: string, data: AnnualTrainingPlanItemBatchUpdateInput) {
  const res = await fetchHrApi(`/hr/annual-training-plans/${id}/items/batch`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新年度计划明细失败',
  })
  revalidatePath('/hr/training/annual-plan')
  return res
}

/** 年度计划明细汇总列表（按年/关键词） */
export async function fetchAnnualPlanItems(params?: { year?: number; keyword?: string }): Promise<{ data: unknown[] }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/annual-plan-items${qs}`, { errorMessage: '加载失败' })
}

/** 上传年度计划明细（Excel） */
export async function uploadAnnualTrainingPlans(formData: FormData): Promise<{ code: number; message: string; data?: unknown }> {
  return fetchHrApi('/hr/annual-training-plans/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

/** 新建单条计划明细 */
export async function createAnnualPlanItem(planId: string, data: Record<string, unknown>) {
  return fetchHrApi(`/hr/annual-training-plans/${planId}/items`, {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建失败',
  })
}

/** 删除单条计划明细 */
export async function deleteAnnualPlanItem(planId: string, itemId: string) {
  return fetchHrApi(`/hr/annual-training-plans/${planId}/items/${itemId}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

// ─── SOP 目录 / 岗位培训内容 ───

export async function fetchSopDepartments(): Promise<{ data: string[] }> {
  return fetchHrApi('/hr/sop-catalog/departments', { errorMessage: '获取部门列表失败' })
}

export async function fetchSopCatalog(params?: {
  department?: string
  page?: number
  page_size?: number
}): Promise<{ data: any[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 200 })
  return fetchHrApi(`/hr/sop-catalog${qs}`, { errorMessage: '加载SOP目录失败' })
}

export async function uploadSopCatalog(formData: FormData): Promise<{ code: number; message: string; data: { created: number; updated: number; errors?: string[] } }> {
  return fetchHrApi('/hr/sop-catalog/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

export async function deleteSopItem(id: string) {
  return fetchHrApi(`/hr/sop-catalog/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

// ─── SOP 培训文件登记表 ───

export async function fetchSopRecordYears(): Promise<{ code: number; message: string; data: string[] }> {
  return fetchHrApi('/hr/sop-training-records/years', { errorMessage: '获取年份失败' })
}

export async function fetchSopTrainingRecords(params?: {
  year?: string
  color?: string
  keyword?: string
}): Promise<{ code: number; message: string; data: SopTrainingRecord[] }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/sop-training-records${qs}`, { errorMessage: '获取登记表失败' })
}

/** 按涉及部门查一级培训师（被培训人员），部门多选自动关联用 */
export async function fetchSopDeptTrainers(departments: string[]): Promise<{
  code: number; message: string; data: { department: string; trainer: string | null }[]
}> {
  const params = new URLSearchParams()
  departments.forEach((d) => params.append('departments', d))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return fetchHrApi(`/hr/sop-training-records/dept-trainers${qs}`, { errorMessage: '获取部门培训师失败' })
}

export async function createSopTrainingRecord(data: Partial<SopTrainingRecord>): Promise<{ code: number; message: string; data: { id: string } }> {
  const res = await fetchHrApi('/hr/sop-training-records', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '登记失败',
  })
  revalidatePath('/hr/training/sop-master')
  revalidatePath('/hr/training/sop-secondary')
  return res
}

export async function updateSopTrainingRecord(id: string, data: Partial<SopTrainingRecord>) {
  const res = await fetchHrApi(`/hr/sop-training-records/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新失败',
  })
  revalidatePath('/hr/training/sop-master')
  revalidatePath('/hr/training/sop-secondary')
  return res
}

/** 提交并通知：自动生成二级表并飞书通知各部门培训管理员 */
export async function submitSopTrainingRecord(id: string): Promise<{ code: number; message: string }> {
  const res = await fetchHrApi(`/hr/sop-training-records/${id}/submit`, {
    method: 'POST',
    errorMessage: '提交失败',
  })
  revalidatePath('/hr/training/sop-master')
  revalidatePath('/hr/training/sop-secondary')
  return res
}

export async function deleteSopTrainingRecord(id: string) {
  const res = await fetchHrApi(`/hr/sop-training-records/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
  revalidatePath('/hr/training/sop-master')
  revalidatePath('/hr/training/sop-secondary')
  return res
}

/** 导出培训文件登记表（对齐模板版式 xlsx） */
export async function exportSopTrainingRecords(year?: string): Promise<{ base64: string; filename: string }> {
  const qs = buildQueryString({ year })
  const { base64, filename } = await fetchHrDownload(`/hr/sop-training-records/export${qs}`, {
    errorMessage: '导出登记表失败',
  })
  return { base64, filename: filename || `培训文件登记表_${year}年.xlsx` }
}

// ─── SOP 培训二级表 ───

export async function fetchSopTrainingEntries(params?: {
  record_id?: string
  department?: string
  status?: string
}): Promise<{ code: number; message: string; data: SopTrainingEntry[] }> {
  const qs = buildQueryString(params || {})
  return fetchHrApi(`/hr/sop-training-entries${qs}`, { errorMessage: '获取二级表失败' })
}

export async function updateSopTrainingEntry(id: string, data: {
  classification?: string
  trainer?: string
  personnel?: SopTrainingPersonnel[]
  complete_time?: string
}) {
  const res = await fetchHrApi(`/hr/sop-training-entries/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '保存失败',
  })
  revalidatePath('/hr/training/sop-secondary')
  return res
}

export async function transferSopTrainingEntry(id: string): Promise<{ code: number; message: string; data: { trainer: string | null } }> {
  const res = await fetchHrApi(`/hr/sop-training-entries/${id}/transfer`, {
    method: 'POST',
    errorMessage: '转培训失败',
  })
  revalidatePath('/hr/training/sop-secondary')
  return res
}

/** 多条SOP一起转训（批量） */
export async function batchTransferSopEntries(ids: string[]): Promise<{ code: number; message: string; data: { transferred: number } }> {
  const res = await fetchHrApi('/hr/sop-training-entries/batch-transfer', {
    method: 'POST',
    body: JSON.stringify({ ids }),
    errorMessage: '批量转培训失败',
  })
  revalidatePath('/hr/training/sop-secondary')
  return res
}

/** 多条SOP生成一套培训材料（zip：每部门一份通知+签到表） */
export async function generateSopTrainingMaterials(ids: string[]): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/sop-training-entries/batch-materials', {
    method: 'POST',
    body: JSON.stringify({ ids }),
    errorMessage: '生成材料失败',
  })
  return { base64, filename: filename || 'SOP培训材料.zip' }
}

export async function fetchSopClassifications(department: string): Promise<{ code: number; message: string; data: SopClassificationOption[] }> {
  const qs = buildQueryString({ department })
  return fetchHrApi(`/hr/sop-training-entries/classifications${qs}`, { errorMessage: '获取分类失败' })
}

export async function fetchSopPersonnel(department: string, classification: string): Promise<{ code: number; message: string; data: SopPersonnelOption[] }> {
  const qs = buildQueryString({ department, classification })
  return fetchHrApi(`/hr/sop-training-entries/personnel${qs}`, { errorMessage: '获取分类人员失败' })
}

/** 导出二级表培训清单（xlsx） */
export async function exportSopTrainingEntries(params?: {
  record_id?: string
  department?: string
  status?: string
}): Promise<{ base64: string; filename: string }> {
  const qs = buildQueryString(params || {})
  const { base64, filename } = await fetchHrDownload(`/hr/sop-training-entries/export${qs}`, {
    errorMessage: '导出培训清单失败',
  })
  return { base64, filename: filename || 'SOP培训清单.xlsx' }
}

export async function fetchPositionTrainings(params: {
  position_name: string
  department?: string
}): Promise<{ data: unknown[] }> {
  const qs = buildQueryString(params)
  return fetchHrApi(`/hr/position-trainings${qs}`, { errorMessage: '加载培训内容失败' })
}

export async function createPositionTraining(data: Record<string, unknown>) {
  return fetchHrApi('/hr/position-trainings', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建失败',
  })
}

// ─── 内训师台账 ───

export async function fetchTrainers(params?: {
  department?: string
  keyword?: string
  is_level1?: string
  page?: number
  page_size?: number
}): Promise<{ data: unknown[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 50 })
  return fetchHrApi(`/hr/trainers${qs}`, { errorMessage: '获取内训师列表失败' })
}

export async function createTrainer(data: Record<string, unknown>) {
  return fetchHrApi('/hr/trainers', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '操作失败',
  })
}

export async function updateTrainer(id: string, data: Record<string, unknown>) {
  return fetchHrApi(`/hr/trainers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '操作失败',
  })
}

export async function deleteTrainer(id: string) {
  return fetchHrApi(`/hr/trainers/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

export async function uploadTrainers(formData: FormData): Promise<{ code: number; message: string; data: { created: number; updated: number } }> {
  return fetchHrApi('/hr/trainers/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

export async function clearTrainers() {
  return fetchHrApi('/hr/trainers', {
    method: 'DELETE',
    errorMessage: '清空失败',
  })
}

// ─── 部门培训人员表 ───

export async function fetchDeptTrainingPersonnel(params?: {
  department?: string
  keyword?: string
  page?: number
  page_size?: number
}): Promise<{ data: unknown[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 50 })
  return fetchHrApi(`/hr/dept-training-personnel${qs}`, { errorMessage: '获取部门培训人员失败' })
}

export async function createDeptTrainingPersonnel(data: Record<string, unknown>) {
  return fetchHrApi('/hr/dept-training-personnel', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '操作失败',
  })
}

export async function updateDeptTrainingPersonnel(id: string, data: Record<string, unknown>) {
  return fetchHrApi(`/hr/dept-training-personnel/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '操作失败',
  })
}

export async function deleteDeptTrainingPersonnel(id: string) {
  return fetchHrApi(`/hr/dept-training-personnel/${id}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}

export async function uploadDeptTrainingPersonnel(formData: FormData): Promise<{ code: number; message: string; data: { created: number; updated: number } }> {
  return fetchHrApi('/hr/dept-training-personnel/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

// ─── Employee Tags ───

export async function fetchEmployeeTags(): Promise<{ code: number; message: string; data: { tag_name: string; count: number }[] }> {
  return fetchHrApi('/hr/employee-tags', { errorMessage: '获取标签列表失败' })
}

export async function saveEmployeeTag(data: { employee_number: string; tag_name: string; action: 'add' | 'remove' }): Promise<{ code: number; message: string }> {
  return fetchHrApi('/hr/employee-tags', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '操作失败',
  })
}

export async function fetchEmployeeTagsByEmployee(employeeNumber: string): Promise<{ code: number; message: string; data: { tag_name: string; created_by: string }[] }> {
  return fetchHrApi(`/hr/employee-tags/by-employee?employee_number=${encodeURIComponent(employeeNumber)}`, { errorMessage: '获取标签失败' })
}

// ─── 员工分类清单（下拉选项模式） ───

export async function fetchEmployeeClassifications(): Promise<{ code: number; message: string; data: { id: string; name: string; count: number }[] }> {
  return fetchHrApi('/hr/employee-classifications', { errorMessage: '获取分类清单失败' })
}

export async function createEmployeeClassification(name: string): Promise<{ code: number; message: string; data: { id: string; name: string } }> {
  return fetchHrApi('/hr/employee-classifications', {
    method: 'POST',
    body: JSON.stringify({ name }),
    errorMessage: '新增分类失败',
  })
}

export async function deleteEmployeeClassification(id: string): Promise<{ code: number; message: string }> {
  return fetchHrApi(`/hr/employee-classifications/${id}`, {
    method: 'DELETE',
    errorMessage: '删除分类失败',
  })
}

export async function fetchClassificationMembers(id: string): Promise<{
  code: number; message: string
  data: { name: string; employee_number: string; department: string; position: string }[]
}> {
  return fetchHrApi(`/hr/employee-classifications/${id}/members`, { errorMessage: '获取分类人员失败' })
}

export async function removeClassificationMembers(id: string, employee_numbers: string[]): Promise<{
  code: number; message: string; data: { removed: number }
}> {
  return fetchHrApi(`/hr/employee-classifications/${id}/remove-members`, {
    method: 'POST',
    body: JSON.stringify({ employee_numbers }),
    errorMessage: '移除人员失败',
  })
}


/** 统筹总表一键生成全套培训材料（通知+签到表+试卷+登记表 zip） */
export async function downloadSopMasterMaterials(recordId: string): Promise<{ base64: string; filename: string | null }> {
  const { base64, filename } = await fetchHrDownload(`/hr/sop-training-records/${recordId}/materials`, { method: 'POST' })
  return { base64, filename: filename || 'SOP全套培训材料.zip' }
}
