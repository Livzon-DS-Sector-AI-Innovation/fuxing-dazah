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

export interface OperationRegulation {
  id: string
  regulation_no: string
  regulation_name: string
  document_path?: string
  document_original_name?: string
  position?: string
  notes?: string
  content?: string        // SOP standardized markdown content
  status?: string         // draft | generated | reviewed | exported
  source_document_path?: string  // original uploaded draft path
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

