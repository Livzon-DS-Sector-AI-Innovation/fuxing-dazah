'use server'

import { revalidatePath } from 'next/cache'
import type {
  QaAssessment,
  QaAssessmentScore,
  QaAssessmentCreateInput,
  QaScoreSaveInput,
  QuestionBankItem,
  ExamGenerateResponse,
  ExamExportData,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'
import { buildQueryString, API_BASE } from './_utils'
import { getAuthHeaders } from '@/lib/auth'

// ─── 问答/实操考核 ───

export async function fetchQaAssessments(params?: {
  department?: string; keyword?: string; page?: number; page_size?: number
}): Promise<{ data: QaAssessment[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi(`/hr/qa-assessments${qs}`, { errorMessage: '获取考核场次列表失败' })
}

export async function fetchQaAssessmentDetail(id: string): Promise<{
  data: { assessment: QaAssessment; scores: QaAssessmentScore[]; statistics: Record<string, unknown> }
}> {
  return fetchHrApi(`/hr/qa-assessments/${id}`, { errorMessage: '获取考核详情失败' })
}

export async function createQaAssessment(data: QaAssessmentCreateInput) {
  return fetchHrApi('/hr/qa-assessments', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建考核场次失败',
  })
}

export async function saveQaAssessmentScores(id: string, data: QaScoreSaveInput) {
  return fetchHrApi(`/hr/qa-assessments/${id}/scores`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '保存成绩失败',
  })
}

export async function deleteQaAssessment(id: string) {
  const res = await fetchHrApi(`/hr/qa-assessments/${id}`, {
    method: 'DELETE',
    errorMessage: '删除考核场次失败',
  })
  revalidatePath('/hr/training/notification')
  return res
}

/** 同步考核成绩到培训台账 */
export async function syncQaAssessmentLedger(id: string) {
  return fetchHrApi<{ code: number; message: string; data?: unknown }>(`/hr/qa-assessments/${id}/sync-ledger`, {
    method: 'POST',
    errorMessage: '同步失败',
  })
}

/** 按优秀/合格比例随机赋分（返回生成结果，供矩阵内继续调整） */
export async function randomizeQaScores(
  id: string,
  params?: { excellent_ratio?: number; pass_ratio?: number; excellent_line?: number; pass_line?: number }
): Promise<{
  code: number; message: string
  data: { generated: number; scores: { employee_name: string; employee_number: string; wrong_questions: number[]; total_score: number; grade: string; result_text: string; assessed_date: string }[] }
}> {
  const qs = buildQueryString({
    excellent_ratio: params?.excellent_ratio,
    pass_ratio: params?.pass_ratio,
    excellent_line: params?.excellent_line,
    pass_line: params?.pass_line,
  })
  return fetchHrApi(`/hr/qa-assessments/${id}/random-scores${qs}`, {
    method: 'POST',
    errorMessage: '随机赋分失败',
  })
}

/** 下载问答实操记录表（docx） */
export async function downloadQaAssessmentRecord(id: string): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/qa-assessments/${id}/export-record`)
  return { base64, filename: filename || '问答实操记录表.docx' }
}

/** 下载培训效果评估表（docx） */
export async function downloadQaAssessmentEvaluation(id: string, expectedCount?: number): Promise<{ base64: string; filename: string }> {
  const qs = buildQueryString({ expected_count: expectedCount })
  const { base64, filename } = await fetchHrDownload(`/hr/qa-assessments/${id}/export-evaluation${qs}`)
  return { base64, filename: filename || '培训效果评估表.docx' }
}

/** 下载考核成绩单（docx） */
export async function downloadQaAssessmentScores(id: string): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/qa-assessments/${id}/export-scores`, {
    errorMessage: '导出失败',
  })
  return { base64, filename: filename || '成绩单.docx' }
}

// ─── 题库 ───

export async function fetchQuestionBank(params?: {
  file_no?: string; keyword?: string; department?: string; page?: number; page_size?: number
}): Promise<{ data: QuestionBankItem[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 50 })
  return fetchHrApi(`/hr/question-bank${qs}`, { errorMessage: '题库检索失败' })
}

export async function addQuestionBankItems(items: {
  file_no?: string; subject?: string; question: string; answer?: string; score?: number; department?: string
}[], source = '手工录入') {
  return fetchHrApi('/hr/question-bank', {
    method: 'POST',
    body: JSON.stringify({ items, source }),
    errorMessage: '题目入库失败',
  })
}

export async function deleteQuestionBankItem(id: string) {
  return fetchHrApi(`/hr/question-bank/${id}`, {
    method: 'DELETE',
    errorMessage: '删除题目失败',
  })
}

/** 从历史记录表（docx）导入题目 */
export async function importQuestionBankDocx(formData: FormData) {
  return fetchHrApi<{ code: number; message: string; data?: unknown }>('/hr/question-bank/import-docx', {
    method: 'POST',
    body: formData,
    errorMessage: '导入失败',
  })
}

// ─── 笔试试卷 ───

export async function fetchExamPapers(params?: {
  department?: string; keyword?: string; page?: number; page_size?: number
}): Promise<{ data: unknown[]; meta?: { total: number } }> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi(`/hr/exam-papers${qs}`, { errorMessage: '获取考卷列表失败' })
}

export async function saveExamPaper(payload: Record<string, unknown>): Promise<{ code: number; message: string; data: unknown }> {
  return fetchHrApi('/hr/exam-papers', {
    method: 'POST',
    body: JSON.stringify(payload),
    errorMessage: '保存考卷失败',
  })
}

/** 下载考卷（docx） */
export async function downloadExamPaper(id: string): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload(`/hr/exam-papers/${id}/download`)
  return { base64, filename: filename || '考卷.docx' }
}

// ─── AI 出题 ───

export async function generateExamQuestions(formData: FormData): Promise<ExamGenerateResponse> {
  const headers = await getAuthHeaders()
  delete headers['Content-Type']
  const res = await fetch(`${API_BASE}/hr/exam/generate`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`出题失败: ${res.status} ${text}`)
  }
  return res.json()
}

/** 导出试卷（docx） */
export async function exportExam(data: ExamExportData): Promise<{ base64: string; filename: string }> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/hr/exam/export`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`导出失败: ${res.status} ${text}`)
  }
  const buffer = Buffer.from(await res.arrayBuffer())
  const safeTitle = data.title.replace(/[\\/:*?"<>|]/g, '_')
  return { base64: buffer.toString('base64'), filename: `${safeTitle}.docx` }
}
