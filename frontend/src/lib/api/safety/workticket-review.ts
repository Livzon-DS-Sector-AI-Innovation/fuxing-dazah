import { apiGet, API_BASE_URL } from '@/lib/http-client'

/** 逐票违规明细（GET /workticket-review/{date} 响应项） */
export interface WorkTicketViolation {
  id: string
  review_id: string
  ticket_no: string
  ticket_type: string
  rule_no: string
  rule_name: string
  detail: string
  key_times: Record<string, unknown> | null
  not_applicable: boolean
}

/** 作业票审核摘要 + 违规明细（一期保留的只读查询端点） */
export interface WorkTicketReviewData {
  date: string
  total: number
  reviewed: number
  violation_count: number
  compliant_count: number
  data_insufficient: number
  status: string
  report_markdown: string | null
  pushed: boolean
  push_message_id: string | null
  error: string | null
  finished_at: string | null
  violations: WorkTicketViolation[]
}

/** 后端 ApiResponse(code=404, HTTP 200) 经 apiGet 透传后的形态 */
interface ApiErrorShape {
  code: number
  message: string
}

function isApiError(v: unknown): v is ApiErrorShape {
  return typeof v === 'object' && v !== null && 'code' in v && 'message' in v
}

/**
 * 查询指定日期的作业票审核摘要与违规明细。
 * 无记录（code=404）返回 null，由调用方渲染空态；网络/HTTP 错误抛 Error。
 */
export async function fetchWorkTicketReview(reviewDate: string): Promise<WorkTicketReviewData | null> {
  const json = await apiGet<WorkTicketReviewData | ApiErrorShape>(
    `${API_BASE_URL}/api/v1/safety/workticket-review/${reviewDate}`,
  )
  if (isApiError(json)) {
    if (json.code === 404) return null
    throw new Error(json.message || '查询作业票审核记录失败')
  }
  return json
}
