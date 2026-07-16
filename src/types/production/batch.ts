import type { Execution } from './execution'

export type ProductionBatchStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled'

export interface ProductionBatch {
  id: string
  batch_no: string
  product_id: string
  route_id: string
  status: ProductionBatchStatus
  quantity: number | null
  unit: string | null
  entry_node_id: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface BatchDetail extends ProductionBatch {
  executions: Execution[]
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
