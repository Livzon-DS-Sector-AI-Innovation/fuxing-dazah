/**
 * Safety 模块共享样式工具
 *
 * 使用方式：
 *   import { statusPill, actionLink, pillTab } from '@/components/safety/shared-styles'
 *
 *   // 状态标签
 *   <span style={statusPill('#1aae39', '#d9f3e1')}>正常</span>
 *
 *   // 操作按钮
 *   <span role="button" onClick={...} style={actionLink('#0075de')}>
 *     <EditOutlined />编辑
 *   </span>
 *
 *   // 筛选 pill tab
 *   <button style={pillTab(active)}>待执行</button>
 */

import type React from 'react'

// ── 状态/结果标签 pill ──
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

// 预设
export const pillSuccess = statusPill('#1aae39', '#d9f3e1')
export const pillWarning = statusPill('#dd5b00', '#ffe8d4')
export const pillError = statusPill('#e03131', '#fde0ec')
export const pillNeutral = statusPill('#787671', '#f0eeec')
export const pillInfo = statusPill('#0075de', '#dcecfa')
export const pillPurple = statusPill('#5645d4', '#e6e0f5')
export const pillDefault = statusPill('#a4a097', '#f0eeec')

// ── 操作按钮 ──
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
export const linkDanger = actionLink('#e03131')
export const linkSuccess = actionLink('#1aae39')
export const linkMuted = actionLink('#787671')
export const linkPurple = actionLink('#5645d4')
export const linkWarning = actionLink('#dd5b00')

// ── 筛选 pill tab ──
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
  fontFamily: 'inherit',
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
  fontFamily: '"JetBrains Mono", "SF Mono", "Fira Code", monospace',
  fontSize: 13,
  color: '#5d5b54',
  letterSpacing: -0.2,
}

// ── 设计 tokens ──
export const T = {
  primary: '#5645d4',
  ink: '#1a1a1a',
  charcoal: '#37352f',
  slate: '#5d5b54',
  steel: '#787671',
  muted: '#a4a097',
  canvas: '#ffffff',
  surface: '#f6f5f4',
  hairline: '#e5e3df',
  hairlineSoft: '#ede9e4',
  cardTintLavender: '#e6e0f5',
} as const
