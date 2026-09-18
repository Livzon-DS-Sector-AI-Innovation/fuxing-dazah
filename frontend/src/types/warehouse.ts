// 仓储管理 - 类型定义
// 对应后端 app/modules/warehouse/schemas.py

import { PaginatedResponse } from '@/types/energy'

// ── 通用 ──

export type MaterialCategory = 'raw' | 'auxiliary' | 'packaging' | 'intermediate' | 'finished'
export type LocationType = 'normal' | 'cold' | 'danger'
export type MovementDirection = 'inbound' | 'outbound' | 'adjust'
export type MovementSourceType = 'purchase' | 'production' | 'sale' | 'return' | 'stocktake' | 'other'

export const MATERIAL_CATEGORY_LABEL: Record<MaterialCategory, string> = {
  raw: '原料',
  auxiliary: '辅料',
  packaging: '包材',
  intermediate: '中间体',
  finished: '成品',
}

export const LOCATION_TYPE_LABEL: Record<LocationType, string> = {
  normal: '常温',
  cold: '冷藏',
  danger: '危险品',
}

export const MOVEMENT_DIRECTION_LABEL: Record<MovementDirection, string> = {
  inbound: '入库',
  outbound: '出库',
  adjust: '盘点调整',
}

export const MOVEMENT_SOURCE_LABEL: Record<MovementSourceType, string> = {
  purchase: '采购入库',
  production: '生产领用/产出',
  sale: '销售出库',
  return: '退料',
  stocktake: '盘点调整',
  other: '其他',
}

// ── 库存状态机（分期D Ticket 03）──

export type StockStatus = 'normal' | 'quarantine' | 'frozen'

export const STOCK_STATUS_LABEL: Record<StockStatus, string> = {
  normal: '正常',
  quarantine: '待检',
  frozen: '冻结',
}

/** 合法流转（与后端 web_stock_status._LEGAL_TRANSITIONS 一致） */
export const STOCK_STATUS_TRANSITIONS: Record<StockStatus, StockStatus[]> = {
  normal: ['quarantine'],
  quarantine: ['normal', 'frozen'],
  frozen: ['normal'],
}

// ── 物料主数据 ──

export interface MaterialRecord {
  id: string
  code: string
  name: string
  category: MaterialCategory
  spec?: string | null
  unit: string
  safety_stock: number
  remark?: string | null
  created_at?: string
  updated_at?: string
}

export interface MaterialCreate {
  code: string
  name: string
  category: MaterialCategory
  spec?: string | null
  unit: string
  safety_stock?: number
  remark?: string | null
}

export interface MaterialUpdate {
  name?: string
  category?: MaterialCategory
  spec?: string | null
  unit?: string
  safety_stock?: number
  remark?: string | null
}

export interface MaterialFilter {
  page?: number
  page_size?: number
  category?: MaterialCategory
  keyword?: string
}

// ── 库位 ──

export interface LocationRecord {
  id: string
  code: string
  name: string
  location_type: LocationType
  remark?: string | null
  created_at?: string
  updated_at?: string
}

export interface LocationCreate {
  code: string
  name: string
  location_type?: LocationType
  remark?: string | null
}

export interface LocationUpdate {
  name?: string
  location_type?: LocationType
  remark?: string | null
}

// ── 库存 ──

export interface StockRecord {
  id: string
  material_id: string
  material_code: string
  material_name: string
  category?: MaterialCategory | null
  unit?: string | null
  safety_stock?: number | null
  batch_no: string
  location_id: string
  location_code: string
  location_name: string
  expiry_date?: string | null
  quantity: number
  status?: StockStatus
  /** QC 闭环状态（warehouse.qc_status 镜像按批号关联，只读；无镜像为 null） */
  qc_sample_status?: string | null
  qc_report_status?: string | null
  qc_release_status?: string | null
}

export interface StockFilter {
  page?: number
  page_size?: number
  category?: MaterialCategory
  keyword?: string
  location_id?: string
  batch_no?: string
  expiry_from?: string
  expiry_to?: string
  status?: StockStatus
}

// ── 出入库 ──

export interface MovementRecord {
  id: string
  movement_no: string
  direction: MovementDirection
  source_type: MovementSourceType
  material_id: string
  material_code: string
  material_name: string
  batch_no: string
  quantity: number
  unit: string
  location_id: string
  location_code: string
  location_name: string
  occurred_at: string
  remark?: string | null
  created_at?: string
}

export interface MovementCreate {
  direction: 'inbound' | 'outbound'
  source_type: Exclude<MovementSourceType, 'stocktake'>
  material_id: string
  batch_no?: string
  quantity: number
  location_id: string
  occurred_at?: string | null
  expiry_date?: string | null
  remark?: string | null
}

export interface MovementFilter {
  material_id?: string | null
  page?: number
  page_size?: number
  direction?: MovementDirection
  source_type?: MovementSourceType
  keyword?: string
  location_id?: string
  occurred_from?: string
  occurred_to?: string
}

// ── 盘点 ──

export interface StocktakeItemRecord {
  id: string
  material_id: string
  material_code: string
  material_name: string
  batch_no: string
  location_id: string
  location_code: string
  location_name: string
  book_quantity: number
  counted_quantity?: number | null
  remark?: string | null
  difference?: number | null
}

export interface StocktakeRecord {
  id: string
  stocktake_no: string
  status: 'draft' | 'confirmed'
  scope_location_id?: string | null
  scope_location_code?: string | null
  scope_location_name?: string | null
  remark?: string | null
  confirmed_at?: string | null
  created_at?: string
  updated_at?: string
  items: StocktakeItemRecord[]
}

export interface StocktakeCreate {
  scope_location_id?: string | null
  remark?: string | null
}

export interface StocktakeItemUpdateInput {
  item_id: string
  counted_quantity?: number | null
  remark?: string | null
}

export interface StocktakeUpdate {
  items: StocktakeItemUpdateInput[]
}

// ── 概览 ──

export interface WarehouseOverview {
  material_count: number
  location_count: number
  stock_sku_count: number
  low_stock_materials: string[]
  today_inbound_quantity: number
  today_outbound_quantity: number
}

// 分页结果沿用全局结构
export type Paginated<T> = PaginatedResponse<T>

// ═══════════════════════════════════════════════════════════════
// 系统配置中心（backend app/modules/warehouse/system_config_api.py，tickets 08+09）
// 类型对齐各 store 的 *View dataclass（GET data.* 数组 / PUT 返回单视图）
// ═══════════════════════════════════════════════════════════════

/** 配置来源（DB 覆盖 > env 兜底 > 代码默认） */
export type WarehouseConfigSource = 'db' | 'env' | 'default'
/** AI 模型位整体状态（五态：含 disabled/missing） */
export type WarehouseProfileStatus = WarehouseConfigSource | 'disabled' | 'missing'

export type WarehouseProfileName = 'agent' | 'agent_backup'
export type WarehouseScenarioName = 'agent_chat' | 'receipt_recognition'

// ── AI 模型配置 ──

export interface WarehouseAiModelConfig {
  api_key?: string
  base_url?: string
  model?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
}

export interface WarehouseAiModelView {
  profile: WarehouseProfileName
  label: string
  /** 最终合并值（DB→env→registry 默认）；api_key 恒为空串（脱敏见 api_key_masked） */
  config: WarehouseAiModelConfig
  api_key_masked: string
  enabled: boolean
  status: WarehouseProfileStatus
  /** 字段级来源（field -> db/env/default） */
  sources: Record<string, WarehouseConfigSource>
}

export interface WarehouseAiModelsData {
  profiles: WarehouseAiModelView[]
}

/** PUT /ai-models/{profile}：api_key 空 = 不修改（前端留空即不带该键） */
export interface WarehouseAiModelUpdateInput {
  base_url?: string
  model?: string
  api_key?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
  enabled?: boolean
  note?: string
}

/** POST /ai-models/test（对已保存配置探测；ok=false 时 error 为摘要） */
export interface WarehouseAiModelTestResult {
  ok: boolean
  model?: string | null
  latency_ms?: number
  status_code?: number
  error?: string
}

// ── AI 场景配置 ──

export interface WarehouseAiScenarioView {
  scenario: WarehouseScenarioName
  label: string
  description: string
  model_type: string
  channel: string
  enabled: boolean
  /** raw 绑定；null = 按场景默认 */
  model_profile: WarehouseProfileName | null
  /** 已解析生效 profile */
  effective_profile: WarehouseProfileName
  allowed_profiles: WarehouseProfileName[]
  source: WarehouseConfigSource | 'disabled'
  status: 'enabled' | 'disabled'
}

export interface WarehouseAiScenariosData {
  scenarios: WarehouseAiScenarioView[]
}

export interface WarehouseAiScenarioUpdateInput {
  enabled?: boolean
  model_profile?: WarehouseProfileName | null
  note?: string
}

// ── 运行参数 ──

export type WarehouseRuntimeValue = string | number | boolean | null

export interface WarehouseRuntimeView {
  key: string
  label: string
  group: string
  value: WarehouseRuntimeValue
  default: WarehouseRuntimeValue
  source: WarehouseConfigSource
  value_type: 'int' | 'float' | 'str'
  min_value: number | null
  max_value: number | null
  max_length: number | null
  description: string
}

export interface WarehouseRuntimeData {
  configs: WarehouseRuntimeView[]
}

// ── 多维表格连接 ──

export interface WarehouseBitableView {
  table_key: string
  base_key: string
  name_cn: string
  /** 脱敏值（****后4位 / 未配置） */
  base_token: string
  table_id: string
  enabled: boolean
  token_source: WarehouseConfigSource
  table_id_source: WarehouseConfigSource
}

export interface WarehouseBitableData {
  connections: WarehouseBitableView[]
}

/** PUT /bitable/connections/{table_key}：空串 = 清空覆盖（回落 env/快照默认） */
export interface WarehouseBitableUpdateInput {
  base_token?: string | null
  table_id?: string | null
  note?: string | null
}

export interface WarehouseBitableTestResult {
  ok: boolean
  table_key?: string
  table_id?: string
  field_count?: number
  error?: string
}

export interface WarehouseBitableRefreshResult {
  ok: boolean
  field_count?: number
  error?: string
}

// ── 定时任务 / 告警目标 ──

/** schedule 三态：interval（seconds ≥30）/ cron（expr）/ null（事件触发，无调度） */
export type WarehouseSchedule =
  | { type: 'interval'; seconds: number }
  | { type: 'cron'; expr: string }
  | null

export interface WarehouseSchedulerTaskView {
  job_name: string
  label: string
  description: string
  enabled: boolean
  schedule: WarehouseSchedule
  target_chat_id: string | null
  source: 'db' | 'default'
}

export interface WarehouseSchedulerData {
  tasks: WarehouseSchedulerTaskView[]
}

export interface WarehouseSchedulerUpdateInput {
  enabled?: boolean
  schedule?: WarehouseSchedule
  target_chat_id?: string | null
  note?: string | null
}

// ── 推送任务（V3.0 分期A 推送订阅中心）──

/** push schedule 四态：daily / weekly（weekday 0=周一）/ monthly / interval；null（事件触发） */
export type WarehousePushSchedule =
  | { type: 'daily'; time: string; window_minutes?: number }
  | { type: 'weekly'; weekday: number; time: string; window_minutes?: number }
  | { type: 'monthly'; day: number; time: string; window_minutes?: number }
  | { type: 'interval'; seconds: number }
  | null

export interface WarehousePushTaskView {
  task_name: string
  scene: string
  label: string
  description: string
  trigger: 'scheduled' | 'event'
  enabled: boolean
  schedule: WarehousePushSchedule
  targets: string[]
  source: 'db' | 'default'
}

export interface WarehousePushTaskData {
  tasks: WarehousePushTaskView[]
}

export interface WarehousePushTaskUpdateInput {
  enabled?: boolean
  schedule?: WarehousePushSchedule
  targets?: string | null
  note?: string | null
}

export interface WarehousePushTriggerResult {
  task_name: string
  scene: string
  status: string
  slot: string | null
  log_count: number
}

export interface WarehousePushLogEntry {
  id: string
  created_at: string
  task_name: string
  scene: string
  trigger: string
  run_at: string
  slot: string | null
  target: string | null
  status: string
  message_id: string | null
  error: string | null
  duration_ms: number | null
}

// ── 配置变更审计（五类端点共用结构，主体键因端点而异）──

export interface WarehouseConfigAuditBase {
  id: string
  action: string
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  operator_name: string | null
  created_at: string
}

export interface WarehouseAiModelAuditItem extends WarehouseConfigAuditBase {
  profile: string
}
export interface WarehouseAiScenarioAuditItem extends WarehouseConfigAuditBase {
  scenario: string
}
export interface WarehouseRuntimeAuditItem extends WarehouseConfigAuditBase {
  key: string
}
export interface WarehouseBitableAuditItem extends WarehouseConfigAuditBase {
  table_key: string
}
export interface WarehouseSchedulerAuditItem extends WarehouseConfigAuditBase {
  job_name: string
}
export interface WarehousePushTaskAuditItem extends WarehouseConfigAuditBase {
  task_name: string
}

/** ConfigAuditSection 的六类审计（决定取数 action 与「对象」列取值键） */
export type WarehouseConfigAuditKind =
  | 'ai-model'
  | 'ai-scenario'
  | 'runtime'
  | 'bitable'
  | 'scheduler'
  | 'push'

// ── AI 调用审计（warehouse.ai_call_audits）──

export interface WarehouseAiAuditListItem {
  id: string
  created_at: string
  scenario: string
  resource: string | null
  model: string
  prompt_version: string | null
  status: 'success' | 'failed'
  error: string | null
  input_tokens: number | null
  output_tokens: number | null
  cache_hit_tokens: number | null
  latency_ms: number | null
  degradation_level: string | null
  trace_id: string | null
  chat_id: string | null
  user_open_id: string | null
  /** {"messages":[...]} 或超限时 {"truncated":true,"preview":"..."} */
  input_json: Record<string, unknown> | null
  /** {"content","tool_calls","reasoning_content"} 或超限截断形态 */
  output_json: Record<string, unknown> | null
  tool_names: string[] | null
  channel: string | null
}

/** 详情端点返回全文形态，与行结构一致（列表已含 json 全文时直接复用） */
export type WarehouseAiAuditDetail = WarehouseAiAuditListItem

export interface WarehouseAiAuditListParams {
  scenario?: string
  status?: string
  trace_id?: string
  page?: number
  page_size?: number
}

/** 统计结构对齐 safety ai-audits/stats（字段可缺省，前端渲染自行兜底） */
export interface WarehouseAiAuditTotals {
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
}

export interface WarehouseAiAuditScenarioStats {
  scenario: string
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  avg_latency_ms: number
}

export interface WarehouseAiAuditStats {
  totals?: WarehouseAiAuditTotals
  prev_totals?: WarehouseAiAuditTotals
  by_scenario?: WarehouseAiAuditScenarioStats[]
  daily?: { date: string; scenario: string; calls: number }[]
}

// ==================== 驾驶舱（V2.0 分期A） ====================

export interface DashboardSummary {
  total_quantity: number
  total_quantity_change: number | null
  material_count: number
  stock_sku_count: number
  today_inbound_quantity: number
  today_inbound_count: number
  today_outbound_quantity: number
  today_outbound_count: number
  yesterday_inbound_quantity: number
  yesterday_outbound_quantity: number
  low_stock_count: number
  draft_stocktake_count: number
  summary_text: string
}

export interface MovementTrendPoint {
  date: string
  inbound: number
  outbound: number
}

export interface StockDistribution {
  by_category: { category: string; total_quantity: number }[]
  by_location_type: { location_type: string; total_quantity: number }[]
}

export interface LowStockItem {
  material_code: string
  material_name: string
  total_quantity: number
  safety_stock: number
}

export interface IdleStockItem {
  material_code: string
  material_name: string
  total_quantity: number
  days_idle: number
  last_inbound_at: string
}

export interface LowStockTop {
  low_stock: LowStockItem[]
  idle: IdleStockItem[]
}

export interface QcPendingItem {
  batch_no: string
  material_name: string
  stage: string
  receipt_date: string | null
}

export interface DashboardTodos {
  low_stock_count: number
  low_stock_items: LowStockItem[]
  draft_stocktakes: { stocktake_no: string; remark: string | null; created_at: string | null }[]
  recent_movements: {
    movement_no: string
    direction: string
    material_name: string
    quantity: number
    unit: string
    occurred_at: string
  }[]
  /** QC 闭环待办（V3.0 分期B 链路4，warehouse.qc_status 镜像） */
  qc_pending: {
    await_sample_count: number
    await_report_count: number
    await_release_count: number
    items: QcPendingItem[]
  }
}

// ==================== 出入库计划单（V2.0 分期A） ====================

export type PlanDirection = 'inbound' | 'outbound'
export type PlanStatus = 'planned' | 'in_progress' | 'completed' | 'cancelled'

export interface MovementPlanRecord {
  id: string
  plan_no: string
  direction: PlanDirection
  source_type: string
  material_id: string
  material_code: string
  material_name: string
  batch_no: string
  quantity: number
  location_id: string
  location_code: string
  location_name: string
  planned_date?: string | null
  status: PlanStatus
  cancel_reason?: string | null
  movement_id?: string | null
  remark?: string | null
}

export interface MovementPlanFilter {
  direction?: PlanDirection
  status?: PlanStatus
  keyword?: string
  planned_before?: string
  page?: number
  page_size?: number
}

export interface MovementPlanCreateInput {
  direction: PlanDirection
  source_type: string
  material_id: string
  batch_no?: string
  quantity: number
  location_id: string
  planned_date?: string | null
  remark?: string | null
}


// ==================== 智能中心（分期B） ====================

export type AlertRuleKey = "low_stock" | "zero_stock" | "idle" | "expiry" | "cover_days"
export type AlertLevel = "warning" | "critical"
export type AlertStatus = "open" | "resolved"

export interface IntelligenceRule {
  rule_key: AlertRuleKey | string
  name: string
  threshold: Record<string, number>
  enabled: boolean
  note?: string | null
}

export interface AlertRecordItem {
  id: string
  rule_key: string
  level: AlertLevel
  status: AlertStatus
  material_code: string
  material_name: string
  batch_no: string
  location_name?: string | null
  detail: Record<string, number | string>
  created_at?: string | null
  resolved_at?: string | null
}

export interface AlertSummary {
  rule_key: string
  text: string
  source: "llm" | "fallback"
  open_count: number
}

export interface ReplenishmentSuggestionItem {
  id: string
  material_code: string
  material_name: string
  avg_daily_outbound: number
  days_cover?: number | null
  suggested_qty: number
  status: "pending" | "handled" | "ignored"
  handled_at?: string | null
}
