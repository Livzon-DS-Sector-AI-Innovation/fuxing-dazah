// ============ Safety Knowledge Article Types ============

import { KnowledgeCategory } from "./enums"

export interface SafetyKnowledgeArticle {
  id: string
  article_no: string | null
  title: string
  category: string
  summary?: string | null
  content?: string | null
  tags?: string | null
  source?: string | null
  author?: string | null
  publish_date?: string | null
  version: number
  superseded_by_id?: string | null
  superseded_by_title?: string | null
  attachment_path?: string | null
  attachment_original_name?: string | null
  view_count: number
  status: string
  notes?: string | null
  knowledge_card?: KnowledgeCardContent | null
  card_version?: number
  created_at: string
  updated_at: string
}

/** 知识卡片 6 维度结构化内容 */
export interface KnowledgeCardContent {
  hazard_type_definitions?: string | null
  hazard_category_criteria?: string | null
  hazard_level_criteria?: string | null
  key_defect_examples?: string | null
  rectification_requirements?: string | null
  legal_basis_clauses?: string | null
}

/** AI 生成知识卡片响应 */
export interface GenerateCardResponse {
  knowledge_card: KnowledgeCardContent
  card_version: number
  message: string
}

/** Agent 注入使用统计 */
export interface AgentUsageStats {
  article_id: string
  article_title: string
  total_injections_30d: number
  by_agent: Record<string, number>
  last_injected_at: string | null
}

/** 批量生成请求 */
export interface BatchGenerateCardsRequest {
  article_ids: string[]
}

/** 批量生成响应 */
export interface BatchGenerateCardsResponse {
  success_count: number
  failed_count: number
  results: { id: string; success: boolean; message: string }[]
}

// ── AI PPT 生成 ──

/** PPT 生成请求 */
export interface GeneratePptRequest {
  template: 'training' | 'briefing' | 'audit'
  style: 'professional' | 'modern' | 'minimal'
}

/** PPT 生成响应 */
export interface GeneratePptResponse {
  download_url: string
  file_name: string
  page_count: number
  message: string
}

/** PPT 生成历史记录 */
export interface PptGenerationRecord {
  id: string
  file_name: string
  template: string
  style: string
  page_count: number
  download_url: string
  created_at: string
}

/** PPT 生成历史列表 */
export interface PptHistoryResponse {
  records: PptGenerationRecord[]
}

// ── AI 摘要生成 ──

/** 摘要生成响应 */
export interface GenerateSummaryResponse {
  summary: string
  message: string
}

export interface SafetyKnowledgeArticleFormData {
  article_no?: string
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

// ── AI 智能解析 ──

export interface ParseDocumentResponse {
  title: string
  category: string
  summary: string
  tags: string
  source: string
  author: string
  publish_date: string | null
  content_preview: string
  full_content: string
}

// ── 重复检测 ──

export interface DuplicateCheckRequest {
  title: string
  content?: string
}

export interface DuplicateArticleItem {
  id: string
  article_no: string | null
  title: string
  category: string
  similarity_reason: string | null
}

export interface DuplicateCheckResponse {
  has_duplicates: boolean
  duplicates: DuplicateArticleItem[]
}

// ── 版本管理 ──

export interface VersionChainItem {
  id: string
  article_no: string | null
  title: string
  version: number
  status: string
  is_current: boolean
  created_at: string
}

export interface NewVersionResponse {
  new_article: SafetyKnowledgeArticle
  version_chain: VersionChainItem[]
}

// ── 语义搜索 ──

export interface SemanticSearchResult {
  id: string
  article_no: string | null
  title: string
  category: string
  summary: string | null
  tags: string | null
  status: string
  match_reason: string | null
}

// ── Bitable 同步 ──

/** Bitable 同步结果 */
export interface SyncKnowledgeResponse {
  created: number
  updated: number
  deleted: number
  total_bitable: number
  total_platform: number
}

// ============ Info Query (RAG Chat) Types ============

export interface InfoQueryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface InfoQueryRequest {
  query: string
  history?: InfoQueryMessage[]
}

export interface InfoQuerySource {
  doc_title: string
  article_ref: string
  chunk_text: string
  doc_category: string
  feishu_url: string
}

export interface InfoQueryResponse {
  answer: string
  sources: InfoQuerySource[]
}
