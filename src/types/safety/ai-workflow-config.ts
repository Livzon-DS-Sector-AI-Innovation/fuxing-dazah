// ============ AI Workflow Config Types ============

/** 调用文档附件项 */
export interface ReferenceAttachment {
  id: string
  /** 附件类型: file（文件上传）/ knowledge（知识库引用） */
  type: 'file' | 'knowledge'
  /** 显示名称 */
  name: string
  /** 预览 URL（浏览器直接打开） */
  url: string
  /** 原始文件名（type=file 时） */
  original_name?: string
  /** 文件类型: pdf / docx / xlsx / txt / md */
  file_type?: string
  /** 文件大小（字节） */
  file_size?: number
  /** 后端转换后的 MD 文件路径（AI 读取用） */
  markdown_path?: string
  /** 知识库文章 ID（type=knowledge 时） */
  knowledge_id?: string
  /** 创建时间 ISO 字符串 */
  created_at: string
}

/** 调用文档完整值 */
export interface ReferenceDocsValue {
  /** 自由文本（标准引用、Skill 说明等） */
  text: string
  /** 附件列表 */
  attachments: ReferenceAttachment[]
}

/** AI 工作流步骤配置（4 字段结构化提示词） */
export interface WorkflowStepItem {
  script_number: number
  name: string
  /** 输入信息 — 工作流需要读取哪些信息 */
  input_info: string
  /** 工作规则 — 明确目的、要求和限制 */
  work_rules: string
  /** 调用文档 — 关联的知识库、参考标准、Skill 等（支持字符串或 {text, attachments} 对象） */
  reference_docs: string | ReferenceDocsValue
  /** 输出格式 — 期望 AI 输出的内容格式 */
  output_format: string
  /** 预期输出键（后端预设，前端不展示） */
  expected_keys: string[]
  is_enabled: boolean
  description?: string
  /** @deprecated 旧格式单 prompt 字段，新格式使用上述 4 字段 */
  prompt_template?: string
}

/** @deprecated 使用 WorkflowStepItem */
export type ScriptConfigItem = WorkflowStepItem

export interface AIWorkflowConfig {
  id: string
  module_code: string
  workflow_name: string
  workflow_description?: string
  trigger_event?: string
  is_enabled: boolean
  script_configs?: WorkflowStepItem[]
  sort_order: number
  notes?: string
  created_at: string
  updated_at: string
}

export interface AIWorkflowConfigFormData {
  module_code: string
  workflow_name: string
  workflow_description?: string
  trigger_event?: string
  is_enabled?: boolean
  script_configs?: WorkflowStepItem[]
  sort_order?: number
  notes?: string
}

export interface AIWorkflowConfigQueryParams {
  page?: number
  page_size?: number
  module_code?: string
  is_enabled?: boolean
}

export const SAFETY_MODULE_OPTIONS = [
  { value: 'hazard-identification', label: '危险源AI辨识', icon: '🤖' },
  { value: 'regulation', label: '安全操规管理', icon: '📋' },
  { value: 'check', label: '安全检查', icon: '✅' },
]

export const TRIGGER_EVENT_OPTIONS = [
  { value: 'submit', label: '提交时触发' },
  { value: 'revision_created', label: '修订创建时触发' },
  { value: 'manual_start', label: '手动启动' },
  { value: 'auto_trigger', label: '自动触发' },
  { value: 'schedule', label: '定时触发' },
]

// ═══════════════════════════════════════════
// AI 工作流 → 菜单分级映射
// ═══════════════════════════════════════════

export interface MenuMapEntry {
  group: string
  subgroup: string
  path: string
}

export const WORKFLOW_MENU_MAP: Record<string, MenuMapEntry> = {
  'hazard-identification': {
    group: '风险与隐患',
    subgroup: '风险分级管控',
    path: '/safety/hazard-identification',
  },
  'special-ops-critical': {
    group: '作业安全',
    subgroup: '特殊作业管理',
    path: '/safety/special-ops',
  },
  'special-ops-export': {
    group: '作业安全',
    subgroup: '特殊作业管理',
    path: '/safety/special-ops',
  },
  'hazard-identification-export': {
    group: '风险与隐患',
    subgroup: '风险分级管控',
    path: '/safety/hazard-identification',
  },
}

export const WORKFLOW_ICONS: Record<string, string> = {
  'hazard-identification': '🤖',
  'special-ops-critical': '🏗️',
  'special-ops-export': '📊',
  'hazard-identification-export': '📋',
}

