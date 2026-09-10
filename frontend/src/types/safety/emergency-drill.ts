// 应急演练管理 — TypeScript 类型（单表模型，三环节：计划→实施→复核）

// ── 数据模型 ──

export interface EnumOption {
  value: string
  label: string
}

// ── 单表数据模型 ──

export interface DrillRecord {
  id: string
  feishu_record_id?: string
  // 计划阶段
  plan_time?: string
  plan_time_ref?: string
  drill_type?: string
  drill_content?: string
  organizer?: string
  department?: string
  organizer_person?: string
  participants?: string
  coop_department?: string
  duration?: string
  notes?: string
  alert_person?: string
  alert_person_data?: Record<string, string>
  // 实施阶段
  execution_time?: string
  drill_plan_file?: string[]
  signin_file?: string[]
  eval_form_file?: string[]
  drill_record_file?: string[]
  eval_ai_file?: string[]
  // 复核阶段
  issues?: string
  rectification_person?: string
  rectification_person_data?: Record<string, string>
  confirmer?: string
  confirmer_data?: Record<string, string>
  status?: string
  // 系统
  is_deleted?: boolean
  created_at?: string
  updated_at?: string
}

export interface DrillRecordQueryParams {
  page?: number
  page_size?: number
  department?: string
  drill_type?: string
  status?: string
  keyword?: string
  stage?: string
}

// ── AI 文档 ──

export interface DrillDocument {
  id: string
  resource_type: string
  resource_id: string
  doc_type: string
  title: string
  content?: string
  content_json?: Record<string, unknown>
  cited_regulations?: { title: string; article: string; excerpt: string }[]
  ai_model?: string
  ai_tokens_used?: number
  version: number
  doc_status: string
  feishu_doc_id?: string
  feishu_doc_url?: string
  feishu_doc_status?: string
  created_at?: string
}

// ── 统计 ──

export interface DrillStats {
  total: number
  executed: number
  completed: number
  pending: number
  by_type: Record<string, number>
  by_department: Record<string, number>
}

// ── 收录记录 ──

export interface CollectionRecord {
  id: string
  feishu_record_id?: string
  upload_date?: string
  attachment?: { name: string; file_token: string }[]
  person_data?: { open_id: string; name: string; email: string }
  department?: string
  parse_status: 'pending' | 'parsed' | 'failed'
  parse_result?: Record<string, unknown>
  stats_record_id?: string
  is_deleted?: boolean
  created_at?: string
  updated_at?: string
}

export interface CollectionStats {
  total: number
  parsed: number
  pending: number
  failed: number
}

// ── 隐患关联 ──

export interface DrillHazardLink {
  hazard_id: string
  hazard_no?: string
  description?: string
  status?: string
  rectification_status?: string
}
