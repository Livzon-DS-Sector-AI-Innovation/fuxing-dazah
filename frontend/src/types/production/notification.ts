// 生产模块通知配置 TypeScript 类型

export interface ProductionNotificationConfig {
  notify_type: string
  name: string
  description: string
  is_enabled: boolean
  extra_user_ids: string[]
}

export interface NotificationConfigUpdateInput {
  is_enabled: boolean
  extra_user_ids: string[]
}
