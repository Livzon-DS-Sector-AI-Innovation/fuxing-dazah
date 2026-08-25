import type { Execution } from './execution'

export type ProductionBatchStatus = 'draft' | 'scheduled' | 'released' | 'pending' | 'in_progress' | 'completed' | 'cancelled'

export interface ProductionBatch {
  id: string
  batch_no: string
  product_id: string
  route_id: string
  route_name: string
  status: ProductionBatchStatus
  quantity: number | null
  unit: string | null
  entry_node_id: string | null
  first_started_at: string | null
  last_finished_at: string | null
  remark: string | null
  created_at: string
  updated_at: string
  owner_user_id?: string | null
  owner_name?: string | null
}

export interface ComputedFieldValue {
  field_key: string
  field_label: string
  unit: string | null
  value: number | null
}

export interface ChildrenAggregateResult {
  field_key: string
  node_code: string | null
  sum: number | null
}

export interface BatchDetail extends ProductionBatch {
  executions: Execution[]
  computed_fields: ComputedFieldValue[]
}

export interface CreateBatchInput {
  batch_no: string
  product_id: string
  route_id: string
  quantity?: number | null
  unit?: string | null
  remark?: string | null
}

export interface ChildBatchInput {
  batch_no: string
  quantity?: number | null
  unit?: string | null
}

export interface DeriveInput {
  edge_id?: string | null
  deviation_reason?: string | null
  children: ChildBatchInput[]
}

export interface MergeInput {
  parents: { batch_id: string; allocated_qty?: number | null }[]
  edge_id?: string | null
  deviation_reason?: string | null
  batch_no: string
  quantity?: number | null
  unit?: string | null
  remark?: string | null
}
