/**
 * Equipment 模块共享样式工具
 *
 * 使用方式：
 *   import { statusPill, actionLink, pillTab } from '@/components/equipment/shared/shared-styles'
 *
 *   // 状态标签
 *   <span style={statusPill('#1aae39', '#d9f3e1')}>正常</span>
 *
 *   // 操作按钮（无 hover）
 *   <span role="button" onClick={...} style={actionLink('#0075de')}>
 *     <EditOutlined />编辑
 *   </span>
 *
 *   // 筛选 pill tab
 *   <button style={pillTab(active)}>待执行</button>
 */

import type React from 'react'

// ── 状态/结果标签 pill ──
// 用法：statusPill('#1aae39', '#d9f3e1')
export const statusPill = (color: string, bg: string): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: '2px 10px',
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  lineHeight: '20px',
  color,
  background: bg,
})

// 预设：语义色
export const pillSuccess = statusPill('#1aae39', '#d9f3e1')
export const pillWarning = statusPill('#dd5b00', '#ffe8d4')
export const pillError   = statusPill('#e03131', '#fde0ec')
export const pillNeutral = statusPill('#787671', '#f0eeec')
export const pillInfo    = statusPill('#0075de', '#dcecfa')
export const pillPurple  = statusPill('#5645d4', '#e6e0f5')

// ── 操作按钮（无 hover，纯文字 + 图标） ──
// 用法：actionLink('#0075de')
export const actionLink = (color: string): React.CSSProperties => ({
  color,
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  background: 'transparent',
  border: 'none',
  padding: 0,
  lineHeight: '22px',
})

// 预设
export const linkPrimary = actionLink('#0075de')
export const linkDanger  = actionLink('#e03131')
export const linkSuccess = actionLink('#1aae39')
export const linkMuted   = actionLink('#787671')
export const linkPurple  = actionLink('#5645d4')
export const linkWarning = actionLink('#dd5b00')

// ── 筛选 pill tab ──
// 用法：<button style={pillTab(active)}>待执行</button>
export const pillTab = (active: boolean): React.CSSProperties => ({
  padding: '4px 14px',
  fontSize: 13,
  fontWeight: 500,
  lineHeight: '22px',
  color: active ? '#ffffff' : '#787671',
  background: active ? '#000000' : 'transparent',
  border: active ? '1px solid #000000' : '1px solid #e5e3df',
  borderRadius: 9999,
  cursor: 'pointer',
})

// ── 表格容器 ──
export const tableCard: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: 12,
  border: '1px solid #e5e3df',
  padding: '4px 24px 24px',
}

// ── 等宽编号字体 ──
export const monoFont: React.CSSProperties = {
  fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
  fontSize: 12,
  color: '#5d5b54',
  letterSpacing: -0.2,
}

// ── 设备状态 pill 配色（唯一数据源：color / bg 对） ──
export const EQUIP_STATUS_PILL_COLORS: Record<string, { color: string; bg: string }> = {
  '完好':     { color: '#1aae39', bg: '#d9f3e1' },
  '备用':     { color: '#0075de', bg: '#dcecfa' },
  '故障待检': { color: '#e03131', bg: '#fde0ec' },
  '维修中':   { color: '#dd5b00', bg: '#ffe8d4' },
  '报废':     { color: '#787671', bg: '#f0eeec' },
}

export const RUNNING_STATUS_PILL_COLORS: Record<string, { color: string; bg: string }> = {
  '开机': { color: '#1aae39', bg: '#d9f3e1' },
  '停机': { color: '#787671', bg: '#f0eeec' },
}

// 衍生：仅前景色（Timeline dot / echarts series / StatsCards）——从上述唯一数据源派生
export const EQUIPMENT_STATUS_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(EQUIP_STATUS_PILL_COLORS).map(([k, v]) => [k, v.color])
)

export const RUNNING_STATUS_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(RUNNING_STATUS_PILL_COLORS).map(([k, v]) => [k, v.color])
)
