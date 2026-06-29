// ============ Safety Knowledge Article Types ============

import { KnowledgeCategory } from "./enums"
export interface SafetyKnowledgeArticle {
  id: string
  article_no: string
  title: string
  category: string
  summary?: string | null
  content?: string | null
  tags?: string | null
  source?: string | null
  author?: string | null
  publish_date?: string | null
  attachment_path?: string | null
  attachment_original_name?: string | null
  view_count: number
  status: string
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SafetyKnowledgeArticleFormData {
  article_no: string
  title: string
  category: KnowledgeCategory
  summary?: string
  content?: string
  tags?: string
  source?: string
  author?: string
  publish_date?: string
  notes?: string
}

export interface SafetyKnowledgeArticleQueryParams {
  page?: number
  page_size?: number
  category?: string
  status?: string
  keyword?: string
}

