// ==================== 关键风险作业报备（Bitable 只读） ====================

export interface KeyRiskOperationPhase {
  date?: string
  photo_url?: string
  issue_desc?: string
}

export interface KeyRiskOperationSubOperation {
  department?: string
  area?: string
  operation_content?: string
  time_slot?: string
  personal_protection?: string
  preparation_measures?: string
  operation_precautions?: string
  emergency_measures?: string
  guardian?: string
}

export interface KeyRiskOperationReport {
  id: string
  report_no: string
  approval_no_url?: string
  source?: string
  feishu_record_id?: string
  // 审批字段
  apply_status?: string
  approval_node?: string
  approval_flow?: string
  current_handler?: string
  initiator_name?: string
  initiator_department?: string
  submitted_at?: string
  completed_at?: string
  // 作业主信息
  department?: string
  area?: string
  operation_content?: string
  start_time?: string
  end_time?: string
  duration_hours?: number
  notes?: string
  // 安全措施（主作业）
  personal_protection?: string
  preparation_measures?: string
  operation_precautions?: string
  emergency_measures?: string
  guardian?: string
  site_guardian?: string
  dept_safety_officer?: string
  // 多作业块 / 三阶段现场确认
  operations?: KeyRiskOperationSubOperation[]
  phase_before?: KeyRiskOperationPhase
  phase_ongoing?: KeyRiskOperationPhase
  phase_after?: KeyRiskOperationPhase
  source_id?: string
  created_at: string
  updated_at: string
}

export interface KeyRiskOperationQueryParams {
  page?: number
  page_size?: number
  department?: string
  area?: string
  operation_content?: string
  apply_status?: string
  date_from?: string
  date_to?: string
  keyword?: string
}

export interface KeyRiskOperationLedgerStats {
  today_approved: number
  in_progress: number
  month_approved: number
  total: number
}

// ── 申请状态配置 ──

export const KEY_RISK_APPLY_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  '已通过': { label: '已通过', color: '#1aae39', bg: '#f0fdf4' },
  '审批中': { label: '审批中', color: '#dd5b00', bg: '#fff7ed' },
  '已拒绝': { label: '已拒绝', color: '#e03131', bg: '#fef2f2' },
  '已取消': { label: '已取消', color: '#787671', bg: '#f6f5f4' },
  '已终止': { label: '已终止', color: '#787671', bg: '#f6f5f4' },
  '已撤回': { label: '已撤回', color: '#787671', bg: '#f6f5f4' },
}

export const KEY_RISK_APPLY_STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: '已通过', label: '已通过' },
  { value: '审批中', label: '审批中' },
  { value: '已拒绝', label: '已拒绝' },
  { value: '已取消', label: '已取消' },
  { value: '已终止', label: '已终止' },
  { value: '已撤回', label: '已撤回' },
]
