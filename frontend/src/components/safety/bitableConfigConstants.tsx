// 多维表格配置中心 UI 常量、soft tag 与微型展示组件
// 配色/圆角/字体全部取自 dazah-frontend/DESIGN.md tokens（Notion 风设计系统）
// 含 JSX（ConfigStatusTag / FieldTypeTag），故为 .tsx
// UI / MONO_FONT / CARD_STYLE 从 schedulerConfigConstants 复用导出，不重复定义（避免 4 处副本漂移）

import { Tag } from 'antd'
import { UI, MONO_FONT, CARD_STYLE } from './schedulerConfigConstants'
import type { BitableConfigStatus, BitableFieldType } from '@/types/safety'

export { UI, MONO_FONT, CARD_STYLE }

// ── 字段类型 8 枚举 → soft tag（浅底深字，色板取自 DESIGN.md tokens） ──
export const FIELD_TYPE_UI: Record<BitableFieldType, { label: string; bg: string; text: string }> = {
  text: { label: '文本', bg: UI.gray, text: UI.slate },
  person: { label: '人员', bg: UI.sky, text: '#005bab' },
  multi_select: { label: '多选', bg: UI.lavender, text: '#391c57' },
  single_select: { label: '单选', bg: UI.yellow, text: '#0a1530' },
  attachment: { label: '附件', bg: UI.rose, text: '#a02e6d' },
  datetime: { label: '日期时间', bg: UI.peach, text: '#793400' },
  enum: { label: '枚举', bg: UI.mint, text: '#1aae39' },
  combined_text: { label: '组合文本', bg: '#f8f5e8', text: '#523410' },
}

export const FIELD_TYPE_OPTIONS: { value: BitableFieldType; label: string }[] = Object.entries(
  FIELD_TYPE_UI,
).map(([value, ui]) => ({ value: value as BitableFieldType, label: ui.label }))

/** 字段类型 soft tag（沿用 ModelTypeTag 渲染范式） */
export function FieldTypeTag({ type }: { type?: BitableFieldType | string | null }) {
  if (!type) return <span style={{ color: UI.muted, fontSize: 12 }}>—</span>
  const ui = FIELD_TYPE_UI[type as BitableFieldType] ?? { label: type, bg: UI.gray, text: UI.steel }
  return (
    <span
      style={{
        display: 'inline-block',
        background: ui.bg,
        color: ui.text,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: '20px',
        padding: '0 8px',
        borderRadius: 6,
        whiteSpace: 'nowrap',
      }}
    >
      {ui.label}
    </span>
  )
}

// ── 配置状态 4 态 badge ──
const CONFIG_STATUS_UI: Record<BitableConfigStatus, { label: string; color: string }> = {
  configured: { label: '已配置', color: 'success' },
  partial: { label: '部分配置', color: 'warning' },
  missing: { label: '未配置', color: 'default' },
  disabled: { label: '已停用', color: 'default' },
}

export function ConfigStatusTag({ status }: { status?: BitableConfigStatus | string | null }) {
  if (!status) return <span style={{ color: UI.muted, fontSize: 12 }}>—</span>
  const ui = CONFIG_STATUS_UI[status as BitableConfigStatus] ?? { label: status, color: 'default' }
  return (
    <Tag color={ui.color} style={{ borderRadius: 6, fontWeight: 600 }}>
      {ui.label}
    </Tag>
  )
}

// ── 审计动作 Tag（含后端 resubscribe 动作） ──
export const ACTION_TAG_UI: Record<string, { label: string; color: string }> = {
  connection_update: { label: '连接更新', color: 'warning' },
  mapping_update: { label: '映射更新', color: 'purple' },
  enable: { label: '启用', color: 'success' },
  disable: { label: '停用', color: 'default' },
  resubscribe: { label: '重订阅', color: 'geekblue' },
}
