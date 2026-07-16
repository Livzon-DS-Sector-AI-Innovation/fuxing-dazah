export interface TraceExecutionBrief {
  node_name: string
  status: string
  owner_name: string | null
  started_at: string
  finished_at: string | null
  is_deviation: boolean
  abnormal_count: number
}

export interface TraceBatch {
  id: string
  batch_no: string
  product_id: string
  status: string
  quantity: number | null
  unit: string | null
  executions: TraceExecutionBrief[]
}

export interface TraceLink {
  parent_batch_id: string
  child_batch_id: string
  edge_id: string | null
  allocated_qty: number | null
  is_deviation: boolean
}

export interface TraceData {
  root_batch_id: string
  batches: TraceBatch[]
  links: TraceLink[]
}
