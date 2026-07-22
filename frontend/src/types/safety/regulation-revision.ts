// ============ RegulationRevision Types ============
import { RevisionType, RevisionScope, ReviewOpinion } from './regulation'

export interface RegulationRevision {
  id: string
  revision_no: string
  regulation_id: string
  regulation_name: string
  old_document_path?: string
  reviser?: string
  reviser_name?: string
  revision_time: string
  revision_type: RevisionType
  revision_opinion?: string
  revision_scope?: string
  review_opinion: ReviewOpinion
  new_document_path?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface RegulationRevisionFormData {
  revision_no: string
  regulation_id: string
  revision_type: RevisionType
  revision_opinion?: string
  reviser?: string
  reviser_name?: string
  notes?: string
}

export interface RegulationRevisionQueryParams {
  page?: number
  page_size?: number
  regulation_id?: string
  revision_type?: string
  review_opinion?: string
  revision_scope?: string
}

