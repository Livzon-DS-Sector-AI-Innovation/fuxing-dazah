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
  product_name: string | null
  status: string
  quantity: number | null
  unit: string | null
  current_stage_name: string | null
  executions: TraceExecutionBrief[]
}

export interface TraceLink {
  parent_batch_id: string
  child_batch_id: string
  /** lineage = 谱系边（derive/merge）；material = 物料边（投料消耗→产出批次） */
  link_type: string
  // lineage 专属
  edge_id: string | null
  allocated_qty: number | null
  is_deviation: boolean
  // material 专属
  intermediate_type_id: string | null
  intermediate_type_name: string | null
  intermediate_batch_no: string | null
  quantity: number | null
  unit: string | null
}

export interface TraceData {
  root_batch_id: string
  batches: TraceBatch[]
  links: TraceLink[]
}
