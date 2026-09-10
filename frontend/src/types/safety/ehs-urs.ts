// URS 智能审核 类型定义（EHS 设备采购合规审核）

export interface URSRiskDimension {
  level: 'high' | 'medium' | 'low'
  indicators: string[]
  evidence: string
}

export interface URSRiskProfile {
  mechanical: URSRiskDimension
  electrical: URSRiskDimension
  data: URSRiskDimension
  environmental: URSRiskDimension
  chemical: URSRiskDimension
}

export interface URSRectificationRequirement {
  item_no: string
  requirement: string
  responsible?: string
  deadline?: string
}

export interface URSReport {
  id: string
  urs_no: string
  equipment_name: string
  equipment_category?: string
  department?: string
  applicant_name?: string
  procurement_purpose?: string
  urs_content?: string
  attachment_path?: string
  notes?: string
  risk_profile?: URSRiskProfile
  overall_risk_level?: string
  risk_profile_reasoning?: string
  ai_confidence?: number
  human_review_comment?: string
  review_result?: {
    score?: number
    grade?: string
    conclusion?: string
    summary?: string
    veto_break?: boolean
  }
  score?: number
  grade?: string
  conclusion?: string
  rectification_requirements?: URSRectificationRequirement[]
  review_status: string
  ai_error_message?: string
  ai_assessment_status?: string
  ai_assessment_completed_at?: string
  appeal_reason?: string
  appeal_result?: {
    old_overall?: string
    reassessed_overall?: string
    basis?: string
  }
  created_at?: string
  updated_at?: string
}

export interface URSStandardItem {
  id: string
  urs_id: string
  item_no: string
  category: string
  risk_dimension?: string
  standard_title: string
  standard_ref?: string
  is_veto: boolean
  source: string
  applicability: string
  applicability_reason?: string
  review_status: string
  review_comment?: string
  ai_suggestion?: string
  rectification_required: boolean
  reviewed_by?: string
  reviewed_at?: string
}

export interface URSQueryParams {
  page?: number
  page_size?: number
  department?: string
  equipment_category?: string
  status?: string
  keyword?: string
}

export interface URSStats {
  total: number
  high_risk: number
  approved: number
  by_status: Record<string, number>
}

// ── 附件解析（parse-upload） ──

export interface URSParsedPoint {
  category: string
  items: string[]
}

export interface ParseUrsDocumentResponse {
  equipment_name: string
  equipment_category: string
  department: string
  procurement_purpose: string
  urs_content: string
  structured_points: URSParsedPoint[]
  attachment_path: string
}
