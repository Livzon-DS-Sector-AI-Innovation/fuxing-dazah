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
  config_schema: ConfigFieldInfo[]
}

// 工具配置表单字段声明（与后端 registry.ConfigField 对齐），驱动配置页动态渲染
export interface ConfigFieldInfo {
  key: string // 点路径，如 feishu.app_id
  label: string // 中文标签
  type: 'text' | 'password' | 'number'
  section: string // 分组标题，空则不分组的默认分组
  required: boolean
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

// 工具配置（与后端 tools/{tool_id}_config.json 结构一致）
export interface ToolConfig {
  feishu: {
    app_id: string
    app_secret: string
  }
  bitable: {
    app_token: string
    shift_table_id: string
    schedule_table_id: string
    whitelist_table_id: string
    attendance_result_table_id: string
    duty_app_token: string
    duty_table_id: string
    actual_clock_table_id: string
  }
  offset_minutes: number
  overtime_gap_minutes: number
}
