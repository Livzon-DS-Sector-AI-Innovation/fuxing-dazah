export type FeedbackType = 'bug' | 'ux' | 'feature'

export interface FeedbackAttachment {
  id: string
  feedback_id: string
  file_name: string
  mime_type: string
  file_size: number
  sha256: string
  uploaded_by_name: string | null
  created_at: string | null
}

export interface Feedback {
  id: string
  type: FeedbackType
  content: string
  page_path: string | null
  submitter_id: string | null
  submitter_name: string
  submitter_department: string | null
  is_handled: boolean
  handled_by_name: string | null
  handled_at: string | null
  created_at: string | null
  updated_at: string | null
  attachments: FeedbackAttachment[]
}

export interface FeedbackCreateInput {
  type: FeedbackType
  content: string
  page_path?: string | null
}

export interface FeedbackListParams {
  page?: number
  page_size?: number
  is_handled?: boolean | null
  type?: FeedbackType | null
}

export const FEEDBACK_TYPE_LABELS: Record<FeedbackType, string> = {
  bug: '缺陷 Bug',
  ux: '优化体验',
  feature: '新增功能',
}

export const FEEDBACK_TYPE_OPTIONS = (Object.keys(FEEDBACK_TYPE_LABELS) as FeedbackType[]).map(
  (value) => ({ value, label: FEEDBACK_TYPE_LABELS[value] }),
)

// 截图限制与后端 app/platform/feedback/service.py 保持一致；前端只做预检，服务端按魔数终裁
export const FEEDBACK_MAX_ATTACHMENTS = 3
export const FEEDBACK_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
export const FEEDBACK_ATTACHMENT_MIME_TYPES = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
] as const
export const FEEDBACK_ATTACHMENT_ACCEPT = FEEDBACK_ATTACHMENT_MIME_TYPES.join(',')
