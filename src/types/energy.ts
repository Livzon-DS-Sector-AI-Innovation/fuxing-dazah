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

// 能耗统计
export interface EnergyStatistics {
  total_electricity: number
  total_water: number
  total_steam: number
  total_cooling: number
  total_compressed_air: number
  total_nitrogen: number
  total_natural_gas: number
  /** @deprecated 保留向后兼容，始终为 0 */
  total_gas: number
}

// 总览数据
export interface EnergyOverviewData {
  summary: EnergyStatistics
  trend: TrendDataPoint[]
  distribution: DistributionDataPoint[]
}

// 统计查询参数
export interface StatisticsParams {
  start_time?: string
  end_time?: string
  energy_type?: EnergyType
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
  rule_name: string
  config_id: string
  device_name: string
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

// 趋势数据点
export interface TrendDataPoint {
  time: string
  value: number
  type: string
}

// 分布数据点
export interface DistributionDataPoint {
  name: string
  value: number
}

// 设备排行数据
export interface DeviceRankItem {
  device_name: string
  value: number
  unit: string
}

// 采集历史查询参数
export interface CollectHistoryParams {
  platform_code?: string   // 默认 zhiheng
  energy_type?: string     // 默认 water
  device_config_id?: string
  start_date: string       // YYYY-MM-DD
  end_date: string         // YYYY-MM-DD
  page?: number
  page_size?: number
}

// 采集历史列表行
export interface CollectHistoryItem {
  device_name: string
  platform_device_code: string
  energy_type: 'water'
  timestamp: string    // ISO datetime
  value: number
  unit: string
}
