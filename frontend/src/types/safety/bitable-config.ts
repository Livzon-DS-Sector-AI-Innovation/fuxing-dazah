// 多维表格配置中心（safety.bitable_config）类型
// 字段严格对齐 dazah-backend/app/modules/safety/schemas/bitable_config.py（Ticket 03 契约）

// ── 枚举 ──

/** Bitable 字段类型 8 枚举（语义对齐 audit/parser.py） */
export type BitableFieldType =
  | 'text'
  | 'person'
  | 'multi_select'
  | 'single_select'
  | 'attachment'
  | 'datetime'
  | 'enum'
  | 'combined_text'

/** 域级配置状态四态（GET /domains config_status） */
export type BitableConfigStatus = 'configured' | 'partial' | 'missing' | 'disabled'

/** kind 级连接视图状态（db=DB 行 / default=registry 默认 / disabled=停用 / missing=无配置） */
export type BitableKindStatus = 'configured' | 'default' | 'disabled' | 'missing'

/** 映射来源（db=DB 行 / default=registry 默认） */
export type BitableMappingStatus = 'db' | 'default'

// ── 映射项（与 PUT /mappings JSONB 语义对齐：源字段/目标字段/类型/默认值/值转换/可选/组合） ──

/** combined_text 专属拼接结构 */
export interface BitableCombinedSpec {
  parts: string[]
  sep: string
  prefix: Record<string, string>
}

export interface BitableFieldMapping {
  /** Bitable 中文列名；combined_text 时可为 null */
  source_field?: string | null
  /** 目标模型字段名（英文 snake_case） */
  target_field: string
  field_type?: BitableFieldType
  /** 解析缺失/失败时的兜底值 */
  default_value?: unknown
  /** enum 专属：源中文值 → 模型枚举，如 {"已关闭": "closed"} */
  value_map?: Record<string, string> | null
  /** true=读取失败仅告警不阻断整条记录 */
  optional?: boolean
  /** 仅 combined_text 类型出现 */
  combined?: BitableCombinedSpec | null
}

// ── 连接行（GET /connections/{domain} 响应项 / PUT /connections/{domain}/{kind} 响应） ──

export interface BitableConnection {
  domain: string
  kind: string
  app_token: string
  table_id: string
  /** 仅 central_alarm 域：白名单其余表 ID（tbl 开头） */
  extra_table_ids?: string[] | null
  enabled: boolean
  note?: string | null
  status: BitableKindStatus
}

// ── 域概览（GET /domains 响应项：14 域注册表 + 每 kind 连接/映射概览） ──

export interface BitableKindSummary {
  kind: string
  label: string
  app_token: string
  table_id: string
  enabled: boolean
  status: BitableKindStatus
  mapping_status: BitableMappingStatus
}

export interface BitableDomainOverview {
  /** 域 key（英文 snake_case，如 central_alarm） */
  key: string
  /** 中文标签（注册表） */
  label: string
  /** 用途说明（注册表） */
  purpose?: string
  /** 订阅方式（drive=文档订阅 / record=记录事件） */
  subscribe?: 'drive' | 'record'
  config_status: BitableConfigStatus
  /** 注册表 kind 清单 + 每 kind 连接/映射概览（含未配置行） */
  kinds: BitableKindSummary[]
  /** 域级说明（如中央报警 15 表白名单），后端未提供时为 null */
  note?: string | null
}

// ── 映射读/写响应（GET/PUT /mappings/{domain}/{kind}） ──

export interface BitableMappingsView {
  domain: string
  kind: string
  status: BitableMappingStatus
  mappings: BitableFieldMapping[]
}

// ── 写入输入 ──

/** PUT /connections/{domain}/{kind} 请求体（enabled/extra_table_ids/note 不传保持现值不变） */
export interface UpdateBitableConnectionInput {
  app_token: string
  table_id: string
  enabled?: boolean
  /** 仅 central_alarm 域支持；显式传 null 表示清空白名单 */
  extra_table_ids?: string[] | null
  note?: string | null
}

/** PUT /mappings/{domain}/{kind} 请求体（JSONB 全量替换） */
export interface UpdateBitableMappingInput {
  mappings: BitableFieldMapping[]
}

// ── 测试连接（POST /test-connection 响应） ──

export interface BitableTestResult {
  ok: boolean
  app_token: string
  table_id: string
  /** 飞书侧拉回的元信息（表/字段样例等） */
  meta?: Record<string, unknown> | null
}

// ── 手动重订阅（POST /resubscribe/{domain} 响应） ──

export interface BitableResubscribeResult {
  domain: string
  /** {kind: ok|skipped|failed} 或 {skipped: True} */
  results: Record<string, unknown>
}

// ── 变更审计（GET /audits，append-only，最新在前） ──

export interface BitableAuditItem {
  id?: string
  domain: string
  kind?: string | null
  action: 'connection_update' | 'mapping_update' | 'enable' | 'disable' | 'resubscribe' | string
  before_json?: Record<string, unknown> | null
  after_json?: Record<string, unknown> | null
  operator_name?: string | null
  created_at: string
}
