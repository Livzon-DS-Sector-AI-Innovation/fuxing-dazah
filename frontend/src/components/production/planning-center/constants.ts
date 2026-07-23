// 计划中枢共享常量 — ponytail: 消除 PlanOrderList/PlanOrderDetailDrawer/PlanItemTable 三处重复

export const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  confirmed: { label: '已确认', color: 'blue' },
  released: { label: '已下达', color: 'purple' },
  completed: { label: '已完成', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
}

export const PRIORITY_CONFIG: Record<string, { label: string; color: string }> = {
  urgent: { label: '紧急', color: 'red' },
  high: { label: '高', color: 'orange' },
  medium: { label: '中', color: 'blue' },
  low: { label: '低', color: 'default' },
}

export const ITEM_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  scheduled: { label: '已排程', color: 'blue' },
  allocated: { label: '已分配', color: 'purple' },
  in_progress: { label: '进行中', color: 'orange' },
  completed: { label: '已完成', color: 'green' },
  cancelled: { label: '已取消', color: 'red' },
}
