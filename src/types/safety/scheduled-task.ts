// ============ Scheduled Tasks (定时任务) ============

export enum ScheduledTaskStatus {
  RUNNING = 'running',
  SUCCESS = 'success',
  FAILURE = 'failure',
}

export const TASK_STATUS_OPTIONS = [
  { value: ScheduledTaskStatus.SUCCESS, label: '成功' },
  { value: ScheduledTaskStatus.FAILURE, label: '失败' },
  { value: ScheduledTaskStatus.RUNNING, label: '运行中' },
]

export enum HeaderColor {
  BLUE = 'blue',
  ORANGE = 'orange',
  GREEN = 'green',
  RED = 'red',
  PURPLE = 'purple',
}

export const HEADER_COLOR_OPTIONS = [
  { value: HeaderColor.BLUE, label: '蓝色', color: '#1677ff' },
  { value: HeaderColor.ORANGE, label: '橙色', color: '#fa8c16' },
  { value: HeaderColor.GREEN, label: '绿色', color: '#52c41a' },
  { value: HeaderColor.RED, label: '红色', color: '#ff4d4f' },
  { value: HeaderColor.PURPLE, label: '紫色', color: '#722ed1' },
]

export const CRON_PRESETS = [
  { label: '每天上午9点', value: '0 9 * * *', desc: '每天上午 09:00' },
  { label: '每天下午6点', value: '0 18 * * *', desc: '每天下午 18:00' },
  { label: '每周一上午9点', value: '0 9 * * 1', desc: '每周一上午 09:00' },
  { label: '每月1号上午9点', value: '0 9 1 * *', desc: '每月1号上午 09:00' },
  { label: '每小时整点', value: '0 * * * *', desc: '每小时整点' },
]

export interface DataSourceItem {
  key: string
  label: string
  enabled: boolean
}

export interface DataSourceOption {
  key: string
  label: string
  description?: string
  default_enabled: boolean
}

export interface ScheduledTask {
  id: string
  name: string
  description?: string
  cron_expression: string
  cron_desc?: string
  feishu_chat_id: string
  feishu_chat_name?: string
  header_color: string
  data_sources: DataSourceItem[]
  card_template?: string
  is_enabled: boolean
  last_run_at?: string
  last_run_status?: string
  last_error?: string
  next_run_at?: string
  created_at: string
  updated_at: string
}

export interface ScheduledTaskLog {
  id: string
  task_id: string
  started_at: string
  completed_at?: string
  status: string
  data_snapshot?: Record<string, string>
  card_content?: string
  feishu_msg_id?: string
  error_message?: string
  duration_ms?: number
  created_at: string
}

export interface ScheduledTaskFormData {
  name: string
  description?: string
  cron_expression: string
  cron_desc?: string
  feishu_chat_id: string
  feishu_chat_name?: string
  header_color: HeaderColor
  data_sources: DataSourceItem[]
  card_template?: string
  is_enabled: boolean
}

export interface ScheduledTaskQueryParams {
  page?: number
  page_size?: number
  is_enabled?: boolean
  search?: string
}

export interface CardPreviewRequest {
  data_sources: DataSourceItem[]
  card_template: string
  header_color: HeaderColor
}

export interface CardPreviewResponse {
  card_json: string
  markdown_preview: string
  variables: Record<string, string>
}

export interface FeishuChat {
  chat_id: string
  name: string
}
