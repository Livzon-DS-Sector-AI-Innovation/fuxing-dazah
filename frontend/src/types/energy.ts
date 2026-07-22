// 能源类型枚举
export type EnergyType =
  | 'electricity'
  | 'water'
  | 'steam'
  | 'cooling'
  | 'compressed_air'
  | 'nitrogen'
  | 'natural_gas'

// 监控级别
export type MonitorLevel = 'normal' | 'important' | 'urgent'

// 数据源配置
export interface EnergyDeviceConfig {
  id: string
  platform_code: string
  platform_device_code: string
  device_name: string
  energy_type: EnergyType
  api_endpoint: string
  workshop: string
  production_line?: string
  monitor_level: MonitorLevel
  unit: string
  collection_interval: number
  is_enabled: boolean
  equipment_id?: string | null
  equipment_name?: string | null
  daily_collect_time?: string | null
  remark?: string
  created_at: string
  updated_at: string
}

// 创建数据源配置输入
export interface CreateDeviceInput {
  platform_code: string
  platform_device_code: string
  device_name: string
  energy_type: EnergyType
  api_endpoint: string
  workshop: string
  production_line?: string
  monitor_level: MonitorLevel
  unit: string
  collection_interval: number
  is_enabled?: boolean
  equipment_id?: string | null
  equipment_name?: string | null
  daily_collect_time?: string | null
  remark?: string
}

// 更新数据源配置输入
export interface UpdateDeviceInput {
  platform_code?: string
  platform_device_code?: string
  device_name?: string
  energy_type?: EnergyType
  api_endpoint?: string
  workshop?: string
  production_line?: string
  monitor_level?: MonitorLevel
  unit?: string
  collection_interval?: number
  is_enabled?: boolean
  equipment_id?: string | null
  equipment_name?: string | null
  daily_collect_time?: string | null
  remark?: string
}

// 设备查询参数
export interface DeviceQueryParams {
  platform_code?: string
  keyword?: string
  energy_type?: EnergyType
  workshop?: string
  is_enabled?: boolean
  page?: number
  page_size?: number
}

// 能耗数据
export interface EnergyData {
  id: string
  config_id: string
  device_name: string
  energy_type: EnergyType
  workshop: string
  production_line?: string
  value: number
  unit: string
  collected_at: string
  created_at: string
}

// 能耗数据历史明细（含设备信息）
export interface EnergyDataHistory {
  id: string
  device_config_id: string
  device_name: string
  platform_device_code: string
  energy_type: string
  workshop: string
  production_line: string | null
  timestamp: string
  value: number
  unit: string
  collected_at: string
  granularity: string  // "true"=按天 "false"=按小时
}

// 能耗数据查询参数
export interface DataQueryParams {
  energy_type?: EnergyType
  workshop?: string
  device_id?: string
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}

// 采集历史查询参数
export interface HistoryQueryParams {
  energy_type?: string
  workshop?: string
  device_config_id?: string
  keyword?: string
  start_time?: string
  end_time?: string
  granularity?: 'daily' | 'hourly'
  page?: number
  page_size?: number
}

// 能耗统计（动态 key）- 已废弃，待采集历史页面使用

// 能源类型元数据（从后端 type_metadata 返回）
export interface EnergyTypeMeta {
  type_code: string
  display_name: string
  unit: string
  color: string | null
  icon: string | null
}

// 分布数据行
export interface DistributionRow {
  group_key: string
  energy_type: string
  total_value: number
  unit: string
  data_count: number
  workshop?: string  // production_line 分组时附带所属车间
}

// 能源总览数据（GET /api/v1/energy/overview）
export interface EnergyOverview {
  summary: Record<string, number>
  trend: { time: string; value: number; type: string }[]
  distribution: DistributionRow[]
  workshop_distribution: DistributionRow[]
  production_line_distribution: DistributionRow[]
  type_metadata: EnergyTypeMeta[]
}

// 采集状态
export type CollectStatus = 'success' | 'partial' | 'failed'

// 采集日志
export interface CollectLog {
  id: string
  platform_code: string
  collect_time: string
  status: CollectStatus
  device_count: number
  success_count: number
  error_message: string | null
  created_at: string
}

// 采集日志设备详情
export interface CollectLogDeviceDetail {
  device_name: string
  platform_device_code: string
  energy_type: string
  value: number
  unit: string
  data_timestamp: string
  data_time_range_end?: string  // 数据覆盖时段终点（整点+1h）
}

// 采集日志详情（含设备数据）
export interface CollectLogDetail {
  id: string
  platform_code: string
  collect_time: string
  status: CollectStatus
  device_count: number
  success_count: number
  error_message: string | null
  created_at: string
  devices: CollectLogDeviceDetail[]
  time_range_start: string | null
  time_range_end: string | null
}

// 采集日志查询参数
export interface LogQueryParams {
  platform_code?: string
  status?: CollectStatus
  page?: number
  page_size?: number
}

// 自动采集运行时设置
export interface CollectSettings {
  auto_collect_enabled: boolean
  auto_collect_interval_seconds: number
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// 预警等级
export type AlertLevel = 'info' | 'warning' | 'critical' | 'emergency'

// 监控指标
export type MonitorMetric = 'instant' | 'daily_total' | 'monthly_total'

// 阈值类型
export type ThresholdType = 'greater_than' | 'less_than' | 'equal'

// 通知频率
export type NotifyFrequency = 'first' | 'every' | 'daily_summary'

// 生效时间类型
export type EffectiveTimeType = 'all_day' | 'custom'

// 预警规则
export interface AlertRule {
  id: string
  rule_name: string
  rule_description?: string
  energy_type: EnergyType
  monitor_metric: MonitorMetric
  threshold_type: ThresholdType
  threshold_value: number
  unit: string
  alert_level: AlertLevel
  notify_method: string[]
  notify_users: string[]
  notify_frequency: NotifyFrequency
  effective_time: EffectiveTimeType
  custom_time_start?: string
  custom_time_end?: string
  is_enabled: boolean
  workshop?: string | null
  is_system: boolean
  created_at: string
  updated_at: string
}

// 创建预警规则输入
export interface CreateRuleInput {
  rule_name: string
  rule_description?: string
  energy_type: EnergyType
  monitor_metric: MonitorMetric
  threshold_type: ThresholdType
  threshold_value: number
  unit: string
  alert_level: AlertLevel
  notify_method: string[]
  notify_users: string[]
  notify_frequency: NotifyFrequency
  effective_time: EffectiveTimeType
  custom_time_start?: string
  custom_time_end?: string
  is_enabled?: boolean
}

// 更新预警规则输入
export interface UpdateRuleInput {
  rule_name?: string
  rule_description?: string
  energy_type?: EnergyType
  monitor_metric?: MonitorMetric
  threshold_type?: ThresholdType
  threshold_value?: number
  unit?: string
  alert_level?: AlertLevel
  notify_method?: string[]
  notify_users?: string[]
  notify_frequency?: NotifyFrequency
  effective_time?: EffectiveTimeType
  custom_time_start?: string
  custom_time_end?: string
  is_enabled?: boolean
}

// 预警规则查询参数
export interface RuleQueryParams {
  energy_type?: EnergyType
  alert_level?: AlertLevel
  is_enabled?: boolean
  page?: number
  page_size?: number
}

// 预警记录状态
export type AlertRecordStatus = 'pending' | 'processed' | 'ignored'

// 预警记录
export interface AlertRecord {
  id: string
  rule_id: string
  device_config_id?: string | null
  workshop?: string | null
  energy_type: EnergyType
  alert_level: AlertLevel
  trigger_value: number
  threshold_value: number
  unit: string
  alert_time: string
  status: AlertRecordStatus
  processed_by?: string
  processed_at?: string
  process_note?: string
  created_at: string
}

// 处理预警记录输入
export interface ProcessRecordInput {
  status: 'processed' | 'ignored'
  process_note?: string
}

// 预警记录查询参数
export interface RecordQueryParams {
  energy_type?: EnergyType
  alert_level?: AlertLevel
  status?: AlertRecordStatus
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}

// 能源类型配置（数据库存储）
export interface EnergyTypeConfig {
  id: string
  type_code: string
  display_name: string
  unit: string
  icon: string | null
  color: string | null
  sort_order: number
  is_enabled: boolean
  parent_code: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface CreateTypeConfigInput {
  type_code: string
  display_name: string
  unit: string
  sort_order?: number
  is_enabled?: boolean
  color?: string | null
  parent_code?: string | null
  remark?: string | null
}

export interface UpdateTypeConfigInput {
  display_name?: string
  unit?: string
  sort_order?: number
  is_enabled?: boolean
  color?: string | null
  parent_code?: string | null
  remark?: string | null
}

// ── 车间预警配置 ──

export interface WorkshopConfig {
  id: string
  workshop: string
  heads: { name: string; feishu_open_id: string }[]
  auto_notify_enabled: boolean
  is_enabled: boolean
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface CreateWorkshopConfigInput {
  workshop: string
  heads?: { name: string; feishu_open_id: string }[]
  auto_notify_enabled?: boolean
  is_enabled?: boolean
}

export interface UpdateWorkshopConfigInput {
  workshop?: string
  heads?: { name: string; feishu_open_id: string }[]
  auto_notify_enabled?: boolean
  is_enabled?: boolean
}

export interface EnergyPersonnelCandidate {
  name: string
  feishu_open_id: string
  department?: string | null
}

