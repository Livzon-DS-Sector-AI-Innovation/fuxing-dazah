// ==================== 人员培训及持证资质智能管理（Cert Warning）====================
//
// 字段名与 `dazah-backend/app/modules/safety/schemas/cert_warnings.py` 实际 schema 对齐
// （后端为权威源）。预警等级 6 档：normal / early_notice / to_schedule /
// key_warning / urgent / overdue；证件类别 3 类：special_op / guardian_a / guardian_b。

// ── 枚举 ──

export enum CertCategory {
  SPECIAL_OP = 'special_op',
  GUARDIAN_A = 'guardian_a',
  GUARDIAN_B = 'guardian_b',
}

export enum WarningLevel {
  NORMAL = 'normal',          // >90 正常
  EARLY_NOTICE = 'early_notice', // 61-90 提前关注
  TO_SCHEDULE = 'to_schedule',   // 31-60 待安排
  KEY_WARNING = 'key_warning',   // 8-30 重点预警
  URGENT = 'urgent',             // 0-7 紧急预警
  OVERDUE = 'overdue',           // <0 已逾期
}

// ── 实体接口（单条到期明细）──

export interface CertWarningDetail {
  id: string
  cert_category: CertCategoryType | string
  person_name: string
  department?: string
  employee_no?: string
  phone?: string
  operation_type?: string
  project?: string
  certificate_no?: string
  issue_date?: string
  next_review_date?: string
  review_frequency?: string
  first_review_deadline?: string
  second_review_deadline?: string
  should_renew_date?: string
  renewed_date?: string
  certificate_file_path?: string
  notes?: string
  // —— 引擎派生字段 ——
  current_node?: string
  deadline?: string
  remaining_days?: number
  status_level: WarningLevel | string
  suggestion?: string
}

// ── 汇总（`get /cert-warnings/summary`）──

export interface CertWarningSummary {
  overdue_count: number
  urgent_count: number
  key_warning_count: number
  to_schedule_count: number
  early_notice_count: number
  normal_count: number
  total: number
  by_category?: Record<string, number>
  by_event?: Record<string, number>
}

// ── 回填请求（`post /{id}/renew`）──

export interface RenewRequest {
  renewed_date?: string | null
  next_review_date?: string | null
  notes?: string
}

// ── 查询参数 ──

export interface CertWarningQueryParams {
  page?: number
  page_size?: number
  status_level?: WarningLevel | string
  department?: string
  cert_category?: CertCategoryType | string
  days_within?: number
}

type CertCategoryType = 'special_op' | 'guardian_a' | 'guardian_b'