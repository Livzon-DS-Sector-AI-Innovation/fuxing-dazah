// Workflow module TypeScript types

// ============ Workflow Definition ============

export interface WorkflowDefCreate {
  name: string
  description?: string | null
  module_code: string
  graph: GraphConfig
  is_enabled?: boolean
}

export interface WorkflowDefUpdate {
  name?: string | null
  description?: string | null
  module_code?: string | null
  graph?: GraphConfig | null
  is_enabled?: boolean | null
}

export interface WorkflowDefResponse {
  id: string
  name: string
  description: string | null
  module_code: string
  graph: GraphConfig
  is_enabled: boolean
  version: number
  created_by: string | null
  is_deleted: boolean
  created_at: string
  updated_at: string
}

// ============ Workflow Run ============

export interface WorkflowRunRequest {
  inputs: Record<string, unknown>
  entity_type?: string | null
  entity_id?: string | null
}

export interface NodeResultEntry {
  status: 'succeeded' | 'failed' | 'skipped'
  output: Record<string, unknown> | null
  error: string | null
  started_at: string | null
  finished_at: string | null
  tokens?: number
  elapsed?: number
}

export interface WorkflowRunResponse {
  id: string
  workflow_id: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown> | null
  node_results: Record<string, NodeResultEntry>
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'stopped'
  total_tokens: number
  total_steps: number
  elapsed_time: number | null
  entity_type: string | null
  entity_id: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

// ============ Graph types (graphon-compatible) ============

export interface GraphNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  sourceHandle: string
  targetHandle: string
}

export interface GraphViewport {
  x: number
  y: number
  zoom: number
}

export interface GraphConfig {
  nodes: GraphNode[]
  edges: GraphEdge[]
  viewport?: GraphViewport
}

// ============ Node type metadata ============

export const NODE_TYPES = [
  { type: 'start', label: 'Start', description: '起始节点 — 定义输入变量', color: '#52c41a' },
  { type: 'end', label: 'End', description: '终止节点 — 定义输出变量', color: '#ff4d4f' },
  { type: 'llm', label: 'LLM', description: '大语言模型调用', color: '#1890ff' },
  { type: 'code', label: 'Code', description: 'Python 代码执行', color: '#722ed1' },
  { type: 'http-request', label: 'HTTP', description: 'HTTP 请求', color: '#13c2c2' },
  { type: 'if-else', label: 'If/Else', description: '条件分支', color: '#fa8c16' },
  { type: 'template-transform', label: 'Template', description: 'Jinja2 模板渲染', color: '#eb2f96' },
  { type: 'variable-aggregator', label: 'Aggregator', description: '变量聚合器', color: '#2f54eb' },
] as const
