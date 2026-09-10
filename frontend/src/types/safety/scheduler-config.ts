// AI 配置 + 定时任务（safety.scheduler_config）类型
// 字段严格对齐 .scratch/ai-config-phase2/backend-design.md 的 API 契约
// 二期（ai-config-phase2）：GET /ai-config 扩展 embedding_model/rerank_model/source/sources，
// PUT /ai-config/{profile}、POST /ai-config/test、GET /ai-config/audits 契约收敛于此。

/** 配置组 profile（后端 registry 注册，前端固定 5 组） */
export type AiModelProfile = 'text' | 'text_backup' | 'vision' | 'embedding' | 'rerank'

/** 生效来源（ProfileView.status：DB 活行 → env 兜底 → registry 默认 / 禁用 / 缺失） */
export type AiConfigSource = 'db' | 'env' | 'default' | 'disabled' | 'missing'

/** AI 模型配置（脱敏视图，二期扩展：dims/source/sources/api_key_set 推导） */
export interface AiModelConfig {
  /** 已合并回退后的实际生效值 */
  base_url: string | null
  model: string | null
  temperature?: number | null
  timeout?: number | null
  /** 向量维度（仅 embedding 组返回） */
  dims?: number | null
  api_key_masked: string
  /** DB 中是否已存 key（后端未直接返回时按 api_key_masked !== '未配置' 推导） */
  api_key_set?: boolean
  /** 生效来源（profile 级结论；text_backup 卡由 backup 构造时可能为 undefined → 隐藏 tag） */
  source?: AiConfigSource
  /** 每字段来源（db/env/default），供展示与调试 */
  sources?: Record<string, string>
  configured: boolean
  /** 文本备用（二期后端维持嵌套 {configured, model, api_key_masked}；text_backup 卡数据源） */
  backup?: AiModelBackupConfig | null
}

/** 文本备用配置（text_model.backup 的嵌套形态；base_url/timeout 后端未返回时为 null） */
export interface AiModelBackupConfig {
  configured: boolean
  model: string | null
  base_url?: string | null
  timeout?: number | null
  api_key_masked: string
  api_key_set?: boolean
  source?: AiConfigSource
}

// ── 三期：场景级调用配置（ai-config-phase3） ──

/** 场景配置生效来源（db=场景级配置生效 / default=按场景类型默认；兼容旧值） */
export type AiScenarioSource = 'db' | 'default' | string

/** AI 调用功能（来自 ai_audit 场景注册表）——三期扩展场景配置状态（向后兼容：旧后端字段缺省） */
export interface AiFunctionItem {
  id: string
  label: string
  description: string
  model_type: 'text' | 'vision'
  channel: string
  /** 三期：场景启用（缺省=旧后端，前端按只读占位处理） */
  enabled?: boolean
  /** 三期：场景级绑定 profile；null=按场景类型默认 */
  model_profile?: AiModelProfile | null
  /** 三期：合并回退后的生效 profile（model_profile || 类型默认） */
  effective_profile?: AiModelProfile | null
  /** 三期：生效来源（db/default；与 profile 级 AiConfigSource 取值域部分重叠，宽松为 string 以兼容） */
  source?: AiScenarioSource | null
  /** 三期：后端状态（enabled/disabled；如绑定非法已回退默认），前端仅 tooltip 使用 */
  status?: string | null
  /** 三期：绑定白名单（后端下发；缺省时前端按 model_type/id 推导） */
  allowed_profiles?: AiModelProfile[] | null
  /** 三期：注册表废弃标记（drill_report_generation 等） */
  deprecated?: boolean
}

/** PUT /scheduler-config/ai-scenarios/{scenario} 响应 data（GET /ai-scenarios 合并视图项同构） */
export interface AiScenarioConfig {
  scenario: string
  enabled: boolean
  model_profile: AiModelProfile | null
  effective_profile: AiModelProfile
  source: AiScenarioSource | AiConfigSource
  status?: string | null
  allowed_profiles?: AiModelProfile[] | null
}

/** PUT /scheduler-config/ai-scenarios/{scenario} 请求体（字段级部分更新） */
export interface UpdateAiScenarioInput {
  enabled?: boolean
  /** null=恢复按场景类型默认；白名单外绑定后端 422 */
  model_profile?: AiModelProfile | null
  /** 备注；None = 保持现值 */
  note?: string
}

/** GET /scheduler-config/ai-scenarios/audits 响应项（append-only，最新在前；结构对齐 AiConfigAuditItem） */
export interface AiScenarioAuditItem {
  id: string
  scenario: string
  action: 'update' | 'enable' | 'disable' | string
  before_json?: Record<string, unknown> | null
  after_json?: Record<string, unknown> | null
  operator_name?: string | null
  created_at: string
}

/** GET /scheduler-config/ai-config 响应 data */
export interface AiConfigData {
  configured?: boolean
  error?: string | null
  text_model: AiModelConfig
  /** 二期：后端若扁平化 text_backup 为顶层则透传；未返回时前端以 text_model.backup 回退构造 */
  text_backup_model?: AiModelConfig | null
  vision_model: AiModelConfig
  embedding_model?: AiModelConfig | null
  rerank_model?: AiModelConfig | null
  functions: AiFunctionItem[]
}

/** PUT /scheduler-config/ai-config/{profile} 请求体（字段级部分更新；api_key 空='' 不修改；不传字段=不改） */
export interface UpdateAiConfigInput {
  base_url?: string
  model?: string
  /** 空串或 undefined 均表示不修改（提交时过滤） */
  api_key?: string
  dims?: number
  temperature?: number
  timeout?: number
  enabled?: boolean
  note?: string
}

/** POST /scheduler-config/ai-config/test 响应 data（后端实际仅返回 ok/status_code/message） */
export interface AiModelTestResult {
  ok: boolean
  status_code?: number | null
  message?: string | null
}

/** GET /scheduler-config/ai-config/audits 响应项（append-only，最新在前；api_key 已后端掩码） */
export interface AiConfigAuditItem {
  id: string
  profile: AiModelProfile | string
  action: 'update' | 'enable' | 'disable' | string
  before_json?: Record<string, unknown> | null
  after_json?: Record<string, unknown> | null
  operator_name?: string | null
  created_at: string
}

/** 定时任务今日/最近运行状态（复用 safety.scheduler_job_runs） */
export interface SchedulerRunState {
  fired_date?: string | null
  status: 'success' | 'failed' | null
  attempt_count?: number
  last_attempt_at?: string | null
  alerted?: boolean
}

/** 定时任务条目（代码默认 + DB 覆写 + 运行状态合并） */
export interface ScheduledTask {
  job_name: string
  description?: string
  hour?: number | null
  minute?: number | null
  dow?: number | null
  enabled: boolean
  /** 发送对象（唯一来源：DB 配置；无目标时为空）；ou_ = 个人 DM，oc_ = 群聊 */
  target_chat_id?: string | null
  target_chat_name?: string | null
  /** 发送对象类型：person（个人 DM）/ group（群聊）；无目标时取任务默认类型 */
  target_type?: 'group' | 'person' | null
  mode?: string | null
  report_type: boolean
  retry_until_hour?: number | null
  retry_until_minute?: number | null
  config_source: 'code' | 'db' | 'db_partial'
  run_state?: SchedulerRunState | null
}

/** 飞书群聊（机器人所在群列表项） */
export interface FeishuGroup {
  chat_id: string
  name: string
  description?: string
  avatar?: string
}

/** 人员（发送对象-个人 DM 候选，已绑定 open_id 的用户） */
export interface FeishuPerson {
  open_id: string
  name: string
  department?: string | null
}

/** PUT /scheduler-config/tasks/{job_name} 请求体 */
export interface UpdateScheduledTaskInput {
  enabled: boolean
  hour?: number | null
  minute?: number | null
  dow?: number | null
  target_chat_id?: string | null
  target_chat_name?: string | null
  retry_until_hour?: number | null
  retry_until_minute?: number | null
}

/** GET /scheduler-config/feishu/groups 响应 data */
export interface FeishuGroupsData {
  items: FeishuGroup[]
  cached_at?: number
  warning?: string | null
}
/** POST /scheduler-config/tasks/{job_name}/preview 响应 data */
export interface SchedulerPreviewData {
  job_name: string
  date: string
  title: string
  markdown: string
}

/** POST /scheduler-config/tasks/{job_name}/run 响应 data */
export interface SchedulerRunResult {
  job_name: string
  success: boolean
  message?: string
  error?: string | null
}
