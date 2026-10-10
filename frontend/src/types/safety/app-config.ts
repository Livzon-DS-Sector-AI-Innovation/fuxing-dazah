// 应用配置中心（safety.app_config）类型
// 字段严格对齐 dazah-backend/app/modules/safety/app_config/store.py（effective_items 视图）

/** 配置类别（后端 registry ConfigCategory） */
export type AppConfigCategory =
  | 'chat_id'
  | 'feature_flag'
  | 'direct_gate'
  | 'poll_param'
  | 'credential'
  | 'misc'

/** 值类型 */
export type AppConfigType = 'bool' | 'int' | 'str'

/** 生效来源：env（进程 env 优先）> db（DB 活行）> default（registry 代码默认） */
export type AppConfigSource = 'env' | 'db' | 'default'

/** 单条配置生效视图（GET /app-config items 项；secret 值后端已脱敏） */
export interface AppConfigItem {
  key: string
  category: AppConfigCategory
  category_label: string
  type: AppConfigType
  /** 生效值（secret 键为 ****后4位 脱敏形态） */
  value: string
  source: AppConfigSource
  /** registry 代码默认值（bool 展示为 true/false） */
  default: string
  description: string
  /** 启动语义键：改动需重启生效（循环启动/import 时读取） */
  restart_required: boolean
  /** 敏感键：展示与审计均脱敏 */
  secret: boolean
  /** str 允许字面量 off（加发群停用哨兵） */
  allow_off: boolean
  /** env 与 DB 同设且值不同：env 优先生效，提示清除 .env 残留键 */
  env_overrides_db: boolean
}

/** GET /app-config 响应 */
export interface AppConfigListData {
  items: AppConfigItem[]
  categories: Record<string, string>
}

/** PUT /app-config/{key} 请求体 */
export interface UpdateAppConfigInput {
  /** 字符串形态（bool 接受 true/false/1/0；str 空串 = 清除覆盖回落 env/默认） */
  value: string
  /** false = 整行停用（回落 env/默认，行保留） */
  enabled?: boolean
  note?: string
}

/** GET /app-config/audits 响应项（before/after 后端已脱敏） */
export interface AppConfigAuditItem {
  key: string
  action: 'update' | 'enable' | 'disable' | 'seed'
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  operator_name: string | null
  created_at: string
}
