/** 知识图谱 TypeScript 类型 — 节点/边/完整图 */

// ── 节点类型 ──────────────────────────────────────────────

export type GraphNodeType = 'document' | 'clause' | 'entity' | 'category' | 'concept'

export type GraphEntityType = 'equipment' | 'condition' | 'location' | 'operation' | 'material' | 'standard'

export type GraphNodeStatus = 'ai_generated' | 'human_confirmed' | 'deprecated' | 'merged'

export interface GraphNode {
  id: string
  name: string
  node_type: GraphNodeType
  aliases?: string[] | null
  article_id?: string | null
  entity_type?: GraphEntityType | null
  ai_summary?: string | null
  confidence?: number | null
  status: GraphNodeStatus
  merged_into_id?: string | null
  metadata?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

// ── 边类型 ────────────────────────────────────────────────

export type GraphRelationType =
  | 'cites'
  | 'supplements'
  | 'replaces'
  | 'belongs_to'
  | 'related_to'
  | 'conflicts_with'

export type GraphEdgeStatus = 'ai_generated' | 'human_confirmed' | 'human_deleted' | 'human_added'

export interface GraphEdge {
  id: string
  source_node_id: string
  target_node_id: string
  relation_type: GraphRelationType
  description?: string | null
  evidence_text?: string | null
  confidence?: number | null
  status: GraphEdgeStatus
  metadata?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

// ── 完整图 ────────────────────────────────────────────────

export interface GraphStats {
  total_nodes: number
  total_edges: number
  by_type: Record<string, number>
  by_status?: Record<string, number>
}

export interface FullGraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

// ── API 查询参数 ──────────────────────────────────────────

export interface GraphQueryParams {
  node_types?: string
  relation_types?: string
  max_nodes?: number
  page?: number
  page_size?: number
  keyword?: string
  node_type?: string
  entity_type?: string
  status?: string
}

export interface GraphExpandParams {
  node_id: string
  hops: number
  relation_types?: string
  max_nodes?: number
}

// ── AI 生成 ───────────────────────────────────────────────

export interface GraphGenerateRequest {
  document_ids?: string[]
  force_rebuild?: boolean
}

export interface GraphGenerateResult {
  status: string
  nodes_created: number
  edges_created: number
  errors: string[]
}
