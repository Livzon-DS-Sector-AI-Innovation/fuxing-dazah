// 工具箱模块类型（与后端 app/modules/toolbox/schemas.py 对齐）

export interface ToolInputInfo {
  key: string
  label: string
  type: 'file' | 'text' | 'textarea' | 'boolean' | 'number' | 'select'
  accept?: string | null
  required: boolean
  multiple: boolean
  default?: unknown
  placeholder?: string | null
  options?: string[] | null
  from_step?: string | null
  from_key?: string | null
}

export interface ToolStepInfo {
  id: string
  name: string
  description: string
  inputs: ToolInputInfo[]
}

export interface ToolInfo {
  id: string
  name: string
  description: string
  image?: string | null
  steps: ToolStepInfo[]
}

export interface StepRunData {
  execution_id: string
  data: Record<string, unknown>
  file_ids: Record<string, string[]> // 恒为列表（单文件也是单元素列表）
}

export interface ExecutionInfo {
  execution_id: string
  tool_id: string
  outputs: Record<string, Record<string, unknown>>
  files: Record<string, { input_key: string; filename: string }>
}
