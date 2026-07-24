/**
 * HR 模块 AI 出题 API
 * 从 lib/api/ai.ts 提取，仅包含 HR 出题相关函数
 */
import { ExamGenerateResponse, ExamExportData } from '@/types/hr'

const BACKEND_BASE = process.env.API_BASE_URL || 'http://127.0.0.1:8000'

export async function generateExamQuestions(
  file: File,
  config?: { choice_count?: number; true_false_count?: number; multi_choice_count?: number; fill_blank_count?: number }
): Promise<ExamGenerateResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (config) {
    formData.append('choice_count', String(config.choice_count ?? 5))
    formData.append('true_false_count', String(config.true_false_count ?? 5))
    formData.append('multi_choice_count', String(config.multi_choice_count ?? 0))
    formData.append('fill_blank_count', String(config.fill_blank_count ?? 0))
  }

  const res = await fetch(`${BACKEND_BASE}/api/v1/hr/exam/generate`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`出题失败: ${res.status} ${text}`)
  }

  return res.json()
}

export async function exportExam(data: ExamExportData): Promise<Blob> {
  const res = await fetch(`${BACKEND_BASE}/api/v1/hr/exam/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`导出失败: ${res.status} ${text}`)
  }

  return res.blob()
}
