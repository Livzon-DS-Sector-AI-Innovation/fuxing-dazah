// 计划中枢共享常量 — ponytail: 消除 PlanOrderList/PlanOrderDetailDrawer/PlanItemTable 三处重复

export const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  confirmed: { label: '已确认', color: 'blue' },
  released: { label: '已下达', color: 'purple' },
  completed: { label: '已完成', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
}

// 计划单状态视觉主题 — 沿 DESIGN.md 语义色：草稿浅灰(未生效) / 已确认蓝 / 已下达紫 / 已完成绿 / 已关闭深灰实心(归档终态)
// tint=徽章/计数背景，text=其上文字，bar=卡片顶条与组头圆点
export const STATUS_THEME: Record<string, { bar: string; tint: string; text: string }> = {
  draft: { bar: '#a4a097', tint: '#f0eeec', text: '#5d5b54' },
  confirmed: { bar: '#0075de', tint: '#dcecfa', text: '#005bab' },
  released: { bar: '#7b3ff2', tint: '#e6e0f5', text: '#391c57' },
  completed: { bar: '#1aae39', tint: '#d9f3e1', text: '#0e8326' },
  closed: { bar: '#37352f', tint: '#37352f', text: '#ffffff' },
}

// 计划单列表分组顺序 = 生命周期推进顺序
export const PLAN_ORDER_STATUS_SEQUENCE = ['draft', 'confirmed', 'released', 'completed', 'closed']

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

// ponytail: 工段色板，CreatePlanOrderModal / PlanOrderDetailDrawer 共用
export const STAGE_PRESET_COLORS = [
  '#e8d5f5',
  '#d5e8f5',
  '#d5f5e0',
  '#f5f0d5',
  '#f5d5d5',
  '#f5e0d5',
  '#d5f5f5',
  '#e0d5f5',
  '#f5d5f0',
  '#d5d5f5',
]
