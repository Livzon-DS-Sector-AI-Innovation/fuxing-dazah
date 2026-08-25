// 中间体台账 TypeScript 类型

export interface IntermediateType {
  id: string
  code: string
  name: string
  category: string | null
  default_unit: string | null
  description: string | null
  is_product: boolean
  product_id: string | null
  product_name: string | null
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export interface CreateIntermediateTypeInput {
  code: string
  name: string
  category?: string
  default_unit?: string
  description?: string
  is_product?: boolean
  product_id?: string | null
}

export interface UpdateIntermediateTypeInput {
  name?: string
  category?: string
  default_unit?: string
  description?: string
  is_product?: boolean
  product_id?: string | null
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
  is_product?: boolean
  sort_order: number
  remark: string | null
}

export interface NodeIntermediateIn {
  intermediate_type_id: string
  direction: 'output' | 'input'
  unit_override?: string
  required?: boolean
  sort_order?: number
  remark?: string
  is_product?: boolean
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
  line_id?: string | null
  line_name?: string | null
  container_id?: string | null  // 混装入库容器
  container_name?: string | null
  available_quantity?: number | null
}

export interface IntermediateOutputIn {
  intermediate_type_id: string
  quantity: number
  unit?: string
  intermediate_batch_no?: string
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
  line_name?: string | null
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

export interface MaterialMovement {
  id: string
  type: 'output' | 'consumption'
  batch_id: string
  batch_no: string | null
  node_name: string | null
  quantity: number
  unit: string
  intermediate_batch_no: string | null
  source_batch_no: string | null
  source_output_id: string | null
  container_name: string | null  // 混装入库容器 / 混装来源容器
  created_at: string
  line_name?: string | null
}

export interface ContainerStock {
  container_id: string
  container_name: string
  available_quantity: number
}

export interface MaterialStockSummary {
  total_output: number
  total_consumed: number
  current_stock: number
  container_stocks: ContainerStock[]
}

export interface MixingContainer {
  id: string
  name: string
  intermediate_type_id: string
  intermediate_type_name: string | null
  line_id: string
  line_name: string | null
  remark: string | null
  available_quantity: number | null
}

export interface MaterialMovements {
  material: IntermediateType
  movements: MaterialMovement[]
  summary: MaterialStockSummary
}
