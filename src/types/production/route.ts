import type { NodeIntermediate, NodeIntermediateIn } from './intermediate'

export type RouteStatus = 'draft' | 'published' | 'archived'
export type EdgeType = 'normal' | 'rework'
export type FieldPhase = 'start' | 'end'
export type FieldDataType = 'numeric' | 'text' | 'boolean' | 'select'

export interface FieldDef {
  id: string
  node_id: string
  field_key: string
  field_label: string
  field_group: string | null
  phase: FieldPhase
  data_type: FieldDataType
  options: string[] | null
  unit: string | null
  required: boolean
  min_value: number | null
  max_value: number | null
  sort_order: number
}

export interface RouteNode {
  id: string
  node_code: string
  name: string
  stage_name: string | null
  node_type: string
  sort_order: number
  fields: FieldDef[]
  intermediates?: NodeIntermediate[]
}

export interface RouteEdge {
  id: string
  from_node_id: string
  to_node_id: string
  edge_type: EdgeType
  is_batch_boundary: boolean
  remark: string | null
}

export interface ProcessRoute {
  id: string
  product_id: string
  version: number
  name: string
  status: RouteStatus
  created_at: string
  updated_at: string
}

export interface RouteGraph {
  route: ProcessRoute
  nodes: RouteNode[]
  edges: RouteEdge[]
}

// ── 编辑入参（对齐后端 RouteGraphIn，边用 node_code 引用） ──

export interface FieldDefIn {
  field_key: string
  field_label: string
  field_group?: string | null
  phase: FieldPhase
  data_type: FieldDataType
  options?: string[] | null
  unit?: string | null
  required: boolean
  min_value?: number | null
  max_value?: number | null
  sort_order: number
}

export interface NodeIn {
  node_code: string
  name: string
  stage_name?: string | null
  node_type?: string
  sort_order: number
  fields: FieldDefIn[]
  intermediates?: NodeIntermediateIn[]
}

export interface EdgeIn {
  from_node_code: string
  to_node_code: string
  edge_type: EdgeType
  is_batch_boundary: boolean
  remark?: string | null
}

export interface RouteGraphIn {
  nodes: NodeIn[]
  edges: EdgeIn[]
}

export interface CreateRouteInput {
  product_id: string
  name: string
}
