// ============ Safety Knowledge Article Types ============

import { KnowledgeCategory } from "./enums"

export interface SafetyKnowledgeArticle {
  id: string
  article_no: string | null
  feishu_record_id?: string | null
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

/** Agent 注入使用统计 */
export interface AgentUsageStats {
  article_id: string
  article_title: string
  total_injections_30d: number
  by_agent: Record<string, number>
  last_injected_at: string | null
}

export interface SafetyKnowledgeArticleQueryParams {
  page?: number
  page_size?: number
  category?: string
  status?: string
  keyword?: string
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
  /** ragplus 条款级命中：命中的条款定位（如「第十四条」/「第7页」） */
  matched_refs?: string[] | null
  /** ragplus 条款级命中：归一相似度 0~1 */
  similarity?: number | null
}

/** ragplus 引擎概览（/knowledge-articles/ragplus-overview） */
export interface RagplusOverview {
  enabled: boolean
  kbs: Array<{ name: string; doc_count: number; chunk_count: number }>
  map_counts: Record<string, number>
  error: string | null
}

/** ragplus 文档映射行（/knowledge-articles/ragplus-doc-map） */
export interface RagplusDocMapEntry {
  status: 'active' | 'failed' | 'archived' | 'deleted'
  version: number
  dataset_name: string
  synced_at: string | null
  last_error: string | null
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

// ── 分类计数（全库） ──

/** 知识库全库统计响应（分类计数 + 状态分布 + 卡片/附件覆盖） */
export interface KnowledgeCategoryCounts {
  total: number
  by_category: Record<string, number>
  by_status: Record<string, number>
  with_card: number
  with_attachment: number
}


// ============ Info Query (RAG Chat) Types ============
// 后端 POST /safety/knowledge/chat 仍然存在，前端函数在合并中丢失，此处恢复。

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
