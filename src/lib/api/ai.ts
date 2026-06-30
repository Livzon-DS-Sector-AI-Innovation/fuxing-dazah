import { ExamGenerateResponse, ExamExportData } from '@/types/hr'

const API_BASE = typeof window !== 'undefined'
  ? '' // 浏览器端使用相对路径（走 Next.js rewrite 代理）
  : (process.env.API_BASE_URL || 'http://127.0.0.1:8000')

export interface ChatAttachment {
  type: 'image'
  mime_type: string
  data: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  reasoning_content?: string
  attachments?: ChatAttachment[]
}

export interface HrPageContext {
  page: string
  filters?: Record<string, string | null | undefined>
  selected_ids?: string[]
  data_summary?: Record<string, string | number | null | undefined>
}

export async function streamChat(
  messages: ChatMessage[],
  pageContext: HrPageContext | null,
  onChunk: (type: 'reasoning' | 'content', text: string) => void,
  onDone: () => void,
  onError: (err: Error) => void,
) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/ai/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages,
        page_context: pageContext,
      }),
    })

    if (!res.ok) {
      const text = await res.text()
      throw new Error(`请求失败: ${res.status} ${text}`)
    }

    const reader = res.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    if (!reader) {
      throw new Error('无法读取响应流')
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            if (data.reasoning_content) {
              onChunk('reasoning', data.reasoning_content)
            }
            if (data.content) {
              onChunk('content', data.content)
            }
            if (data.done) onDone()
          } catch {
            // ignore malformed lines
          }
        }
      }
    }

    onDone()
  } catch (err: any) {
    onError(err instanceof Error ? err : new Error(String(err)))
  }
}

// ─── AI 出题 API ───

const BACKEND_BASE = process.env.API_BASE_URL || 'http://127.0.0.1:8000'

export async function generateExamQuestions(
  file: File,
  config?: { choice_count?: number; true_false_count?: number; qa_count?: number }
): Promise<ExamGenerateResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (config) {
    formData.append('choice_count', String(config.choice_count ?? 5))
    formData.append('true_false_count', String(config.true_false_count ?? 5))
    formData.append('qa_count', String(config.qa_count ?? 0))
  }

  const res = await fetch(`${BACKEND_BASE}/api/v1/ai/exam/generate`, {
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
  const res = await fetch(`${BACKEND_BASE}/api/v1/ai/exam/export`, {
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
