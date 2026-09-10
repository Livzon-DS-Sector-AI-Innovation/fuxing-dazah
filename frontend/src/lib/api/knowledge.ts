import type { SafetyKnowledgeArticle, KnowledgeCategoryCounts } from '@/types/safety'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export interface KnowledgeListParams {
  page?: number
  page_size?: number
  status?: string
  category?: string
  keyword?: string
}

export interface KnowledgePage {
  items: SafetyKnowledgeArticle[]
  total: number
  page: number
  page_size: number
}

/** 知识库文档列表（分页） */
export async function fetchKnowledgeArticles(params?: KnowledgeListParams): Promise<KnowledgePage> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.category) sp.set('category', params.category)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/knowledge-articles${qs ? `?${qs}` : ''}`)
}

/** 语义搜索（AI 解析查询意图，返回字段可能不完整） */
export async function fetchKnowledgeSemanticSearch(
  q: string,
  page = 1,
  page_size = 48,
): Promise<KnowledgePage> {
  const sp = new URLSearchParams({ q, page: String(page), page_size: String(page_size) })
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/knowledge-articles/semantic-search?${sp.toString()}`)
}

/** 全库分类统计（独立于列表分页） */
export async function fetchKnowledgeCategoryCounts(): Promise<KnowledgeCategoryCounts> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/knowledge-articles/category-counts`)
}
