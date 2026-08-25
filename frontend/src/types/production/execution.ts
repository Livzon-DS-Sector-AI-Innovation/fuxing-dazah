export type ExecutionStatus = 'in_progress' | 'completed' | 'aborted'

export interface FieldValue {
  field_key: string
  field_label: string
  unit: string | null
  phase: 'start' | 'end'
  value_text: string | null
  value_numeric: number | null
  value_bool: boolean | null
  is_abnormal: boolean
  remark: string | null
}

export interface EquipmentSnapshot {
  equipment_id: string
  equipment_no: string
  equipment_name: string
}

export interface Execution {
  id: string
  batch_id: string
  node_id: string
  node_name: string | null
  execution_seq: number
  status: ExecutionStatus
  owner_id: string | null
  owner_name: string | null
  started_at: string
  started_by_name: string | null
  finished_at: string | null
  finished_by_name: string | null
  is_deviation: boolean
  deviation_reason: string | null
  remark: string | null
  equipments: EquipmentSnapshot[]
  field_values: FieldValue[]
  missing_required_fields?: MissingField[]
}

export interface MissingField {
  field_key: string
  field_label: string
}

export interface FieldValueInput {
  field_key: string
  value: boolean | number | string | null
}

export interface StartExecutionInput {
  node_id: string
  owner_id?: string | null
  owner_name?: string | null
  equipment_ids?: string[]
  field_values?: FieldValueInput[]
  deviation_reason?: string | null
  remark?: string | null
  intermediate_consumptions?: Array<{
    intermediate_type_id: string
    output_id?: string | null  // 精确消耗：选产出批次（与 container_id 二选一）
    container_id?: string | null  // 混装消耗：选容器
    quantity: number
    unit?: string
    remark?: string
  }>
  started_at?: string | null
}

export interface CompleteExecutionInput {
  field_values?: FieldValueInput[]
  remark?: string | null
  intermediate_outputs?: Array<{
    intermediate_type_id: string
    quantity: number
    unit?: string
    intermediate_batch_no?: string
    container_id?: string | null  // 选容器则混装入库
    remark?: string
  }>
  line_id?: string | null
  finished_at?: string | null
}

export interface NodeExecutionListItem {
  id: string
  batch_id: string
  batch_no: string
  execution_seq: number
  status: ExecutionStatus
  owner_name: string | null
  started_at: string
  finished_at: string | null
  is_deviation: boolean
  abnormal_count: number
}
