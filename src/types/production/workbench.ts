export interface NodeAssigneeInfo {
  user_id: string
  name: string | null
}

export interface WorkbenchItem {
  type: 'pending_receive' | 'pending_start' | 'pending_complete' | 'ready_to_complete'
  batch_no: string | null
  batch_id: string | null
  product_name: string | null
  route_id: string
  route_name: string
  route_version: number | null
  node_id: string
  node_name: string
  stage_name: string | null
  predecessor_batches: string[]
  node_assignees: NodeAssigneeInfo[]
  boundary_edge_id: string | null
  parent_batch_ids: string[]
  execution_id: string | null
  execution_seq: number | null
  owner_name: string | null
  started_at: string | null
  is_last_in_stage: boolean
}

export interface AssignedNodeInfo {
  node_id: string
  node_name: string
}

export interface AssignedStageInfo {
  stage_name: string
  nodes: AssignedNodeInfo[]
}

export interface AssignedRouteInfo {
  route_id: string
  route_name: string
  route_version: number | null
  product_name: string | null
  stages: AssignedStageInfo[]
}

export interface RecentCompletedItem {
  batch_no: string | null
  batch_id: string | null
  product_name: string | null
  route_id: string
  route_name: string
  node_id: string
  node_name: string
  stage_name: string | null
  execution_id: string | null
  owner_name: string | null
  finished_at: string | null
}

export interface WorkbenchData {
  role: 'stage_owner' | 'node_owner'
  stage_names: string[]
  assigned_routes: AssignedRouteInfo[]
  items: WorkbenchItem[]
  recent_completed: RecentCompletedItem[]
}

export interface StageAssignment {
  id: string
  user_id: string
  stage_name: string
  route_id: string
  created_at: string
}

export interface NodeAssignment {
  id: string
  user_id: string
  node_id: string
  route_id: string
  assigned_by: string
  created_at: string
}

export interface ChildInput {
  batch_no: string
  quantity?: number
  unit?: string
}

export interface ExecutionInput {
  node_id: string
  owner_id?: string | null
  owner_name?: string | null
  equipment_ids?: string[]
  field_values?: FieldValueInput[]
  intermediate_consumptions?: IntermediateConsumptionInput[]
  remark?: string | null
}

export interface FieldValueInput {
  field_key: string
  value_text?: string
  value_numeric?: number
  value_bool?: boolean
}

export interface IntermediateConsumptionInput {
  intermediate_type_id: string
  output_id: string
  quantity: number
  remark?: string
}

export interface ReceiveAndStartInput {
  parent_batch_ids: string[]
  edge_id?: string | null
  deviation_reason?: string | null
  children: ChildInput[]
  start_execution: boolean
  execution?: ExecutionInput | null
}

export interface ReceiveAndStartResult {
  children: Array<{ id: string; batch_no: string }>
  execution: unknown | null
}
