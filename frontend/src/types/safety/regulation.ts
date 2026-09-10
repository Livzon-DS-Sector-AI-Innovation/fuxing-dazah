// ============ Regulation Enums ============

export enum RevisionType {
  MANUAL = 'manual',
  AI = 'ai',
}

export const REVISION_TYPE_OPTIONS = [
  { value: RevisionType.MANUAL, label: '人工修订' },
  { value: RevisionType.AI, label: 'AI修订' },
]

export enum RevisionScope {
  PROCESS = 'process',
  SAFETY_REQUIREMENT = 'safety_requirement',
}

export const REVISION_SCOPE_OPTIONS = [
  { value: RevisionScope.PROCESS, label: '工艺' },
  { value: RevisionScope.SAFETY_REQUIREMENT, label: '安全要求' },
]

export enum ReviewOpinion {
  PENDING = 'pending',
  APPROVED = 'approved',
}

export const REVIEW_OPINION_OPTIONS = [
  { value: ReviewOpinion.PENDING, label: '待审核', color: 'default' },
  { value: ReviewOpinion.APPROVED, label: '已审核', color: 'success' },
]


// ============ OperationRegulation Types ============

/** AI 审核维度结论 */
export interface AiReviewDimension {
  dimension: string
  status: 'pass' | 'warn' | 'fail'
  detail: string
}

/** AI 审核按章节修正建议 */
export interface AiReviewChapterFix {
  chapter: number
  title: string
  action: 'keep' | 'rewrite' | 'append'
  corrected_content: string
  note: string
}

/** 视觉审核页级排版布局问题 */
export interface AiReviewLayoutIssue {
  page: number
  issue_type: string
  severity: 'warn' | 'fail'
  description: string
}

/** AI 审核说明（ai_review_note 落库结构） */
export interface AiReviewNote {
  summary: string
  dimensions: AiReviewDimension[]
  chapter_fixes: AiReviewChapterFix[]
  /** 视觉审核的页级排版问题（可选：视觉通道未执行或未发现问题时缺失） */
  layout_issues?: AiReviewLayoutIssue[]
  /** 视觉审核整体结论（layout_issues 各页问题之外的总体评价） */
  layout_summary?: string
  reviewed_at?: string
}

export interface OperationRegulation {
  id: string
  regulation_no: string
  regulation_name: string
  document_path?: string
  document_original_name?: string
  position?: string
  notes?: string
  content?: string        // SOP standardized markdown content
  status?: string         // draft | generated | reviewed | exported | ai_reviewed
  source_document_path?: string  // original uploaded draft path
  ai_review_status?: 'pending' | 'reviewing' | 'completed' | 'failed'
  ai_review_note?: AiReviewNote
  created_at: string
  updated_at: string
}

export interface OperationRegulationFormData {
  regulation_no: string
  regulation_name: string
  position?: string
  notes?: string
}

export interface OperationRegulationQueryParams {
  page?: number
  page_size?: number
  position?: string
  keyword?: string
  status?: string
}

