// 工具箱模块类型（与后端 app/modules/toolbox/schemas.py 对齐）

export interface ToolInputInfo {
  key: string
  label: string
  type: 'file' | 'text' | 'textarea' | 'boolean' | 'number' | 'select' | 'month' | 'date'
  accept?: string | null
  required: boolean
  multiple: boolean
  default?: unknown
  placeholder?: string | null
  // select 可选项：字符串（显示=提交值）或 {value, label}（显示中文 label、提交英文枚举值）
  options?: Array<string | { value: string; label: string }> | null
  from_step?: string | null
  from_key?: string | null
  show_when?: [string, string] | null // (字段 key, 值) 命中时才显示该输入
  help?: string | null // 参数用途说明，label 旁问号气泡展示
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
  can_use: boolean
  can_config: boolean
  background: boolean // 后台执行工具：run 返回 running，轮询会话状态取结果
}

// 工具配置表单字段声明（与后端 registry.ConfigField 对齐），驱动配置页动态渲染
export interface ConfigFieldInfo {
  key: string // 点路径，如 feishu.app_id
  label: string // 中文标签
  type: 'text' | 'password' | 'number' | 'textarea'
  section: string // 分组标题，空则不分组的默认分组
  required: boolean
  help?: string | null // 字段用途说明，label 旁问号气泡展示
}

export interface StepRunData {
  execution_id: string
  data: Record<string, unknown>
  file_ids: Record<string, string[]> // 恒为列表（单文件也是单元素列表）
  warning?: string | null // 执行成功但记录落库失败时的提示；正常为 null
  status?: 'done' | 'running' // running=后台执行已启动（data 为空），结果轮询会话获取
}

/** 某步骤的执行进度（后台执行工具，会话 progress 字段）。 */
export interface StepProgress {
  percent: number
  message: string
  status: 'running' | 'done' | 'failed'
  error?: string | null
  updated_at?: number
}

export interface ExecutionInfo {
  execution_id: string
  tool_id: string
  outputs: Record<string, Record<string, unknown>>
  files: Record<string, { input_key: string; filename: string }>
  progress?: Record<string, StepProgress>
}

/** 执行会话列表摘要（后端 ExecutionSummaryOut，当前用户、跨工具）。 */
export interface ExecutionSummaryInfo {
  execution_id: string
  tool_id: string
  status: 'running' | 'done' | 'failed'
  percent: number
  message: string
  error: string
  created_at: number
}

// 工具配置（结构因工具而异，后端存储任意 JSON 对象）
export type ToolConfig = Record<string, unknown>

// ── 使用权限管理 ──

/** 授权名单中的用户（后端 GrantUserOut） */
export interface ToolGrantUser {
  user_id: string
  name: string
  employee_no?: string | null
  department?: string | null
}

/** 某工具的使用/配置授权名单（后端 ToolGrantsOut） */
export interface ToolGrantInfo {
  tool_id: string
  tool_name: string
  use_users: ToolGrantUser[]
  config_users: ToolGrantUser[]
}

/** 人员选择器选项（identity/personnel 列表的精简映射） */
export interface PersonnelOption {
  id: string
  name: string
  employee_no?: string | null
  department?: string | null
}
