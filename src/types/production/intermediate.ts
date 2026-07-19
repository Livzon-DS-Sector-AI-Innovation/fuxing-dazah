// 中间体台账 TypeScript 类型

export interface IntermediateType {
  id: string
  code: string
  name: string
  category: string | null
  default_unit: string | null
  description: string | null
  created_at: string
  updated_at: string
}

export interface CreateIntermediateTypeInput {
  code: string
  name: string
  category?: string
  default_unit?: string
  description?: string
}

export interface UpdateIntermediateTypeInput {
  name?: string
  category?: string
  default_unit?: string
  description?: string
}

// 节点中间体绑定（模板层）
export interface NodeIntermediate {
  id: string
  node_id: string
  intermediate_type_id: string
  intermediate_type_name?: string
  direction: 'output' | 'input'
  unit_override: string | null
  required: boolean
  is_product: boolean
  sort_order: number
  remark: string | null
}

export interface NodeIntermediateIn {
  intermediate_type_id: string
  direction: 'output' | 'input'
  unit_override?: string
  required?: boolean
  is_product?: boolean
  sort_order?: number
  remark?: string
}

// 中间体产出记录
export interface IntermediateOutput {
  id: string
  batch_id: string
  batch_no?: string
  execution_id: string
  node_id: string
  node_name?: string
  intermediate_type_id: string
  intermediate_type_name?: string
  intermediate_batch_no: string | null
  quantity: number
  unit: string
  is_product: boolean
  remark: string | null
  created_at: string
}

export interface IntermediateOutputIn {
  intermediate_type_id: string
  quantity: number
  unit?: string
  intermediate_batch_no?: string
  is_product?: boolean
  remark?: string
}

// 中间体消耗记录
export interface IntermediateConsumption {
  id: string
  batch_id: string
  batch_no?: string
  execution_id: string
  node_id: string
  node_name?: string
  intermediate_type_id: string
  intermediate_type_name?: string
  output_id: string
  output_batch_no?: string
  quantity: number
  unit: string
  remark: string | null
  created_at: string
}

export interface IntermediateConsumptionIn {
  intermediate_type_id: string
  output_id: string
  quantity: number
  unit?: string
  remark?: string
}

// 追溯
export interface IntermediateTrace {
  output: IntermediateOutput
  consumptions: IntermediateConsumption[]
}
