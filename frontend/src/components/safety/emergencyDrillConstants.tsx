// 应急演练管理 — UI 常量 & 视觉映射
// 配色取自 DESIGN.md tokens，参考 AiAuditConstants 模式

import {
  FireOutlined,
  AlertOutlined,
  ExperimentOutlined,
  MedicineBoxOutlined,
  DesktopOutlined,
  TeamOutlined,
  ToolOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { T } from './shared-styles'

// ── 演练类型 → 视觉 ──

export interface DrillTypeUi {
  label: string
  bg: string
  text: string
  icon: React.ReactNode
}

export const DRILL_TYPE_UI: Record<string, DrillTypeUi> = {
  '应急疏散演练': { label: '应急疏散', bg: T.peach, text: '#793400', icon: <FireOutlined /> },
  '现场岗位处置': { label: '岗位处置', bg: T.mint, text: '#1aae39', icon: <ToolOutlined /> },
  '专项应急演练': { label: '专项演练', bg: T.lavender, text: '#391c57', icon: <AlertOutlined /> },
  '综合应急演练': { label: '综合演练', bg: T.sky, text: '#005bab', icon: <ApartmentOutlined /> },
  '消防器材培训': { label: '消防培训', bg: T.rose, text: '#a02e6d', icon: <ExperimentOutlined /> },
}

// ── 复核状态 → 视觉 ──

export const REVIEW_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  '已完成': { label: '已完成', color: '#1aae39', bg: T.mint },
  '未完成': { label: '未完成', color: T.warning, bg: T.peach },
}

// ── 环节标签 ──

export const STAGE_UI: Record<string, { label: string; color: string; bg: string }> = {
  plan: { label: '计划', color: '#0075de', bg: T.sky },
  execution: { label: '实施', color: T.warning, bg: T.peach },
  review: { label: '复核', color: T.primary, bg: T.lavender },
}

// ── 设计 tokens 快捷引用 ──
export { T }
export const UI = {
  canvas: '#ffffff',
  surface: '#f6f5f4',
  hairline: '#e5e3df',
  ink: '#1a1a1a',
  stone: '#5d5b54',
  steel: '#787671',
  muted: '#a4a097',
}

export const CARD_STYLE: React.CSSProperties = {
  background: UI.canvas,
  border: `1px solid ${UI.hairline}`,
  borderRadius: 12,
}

// ── 筛选选项 ──

export const DRILL_TYPE_FILTER = [
  { value: '', label: '全部类型' },
  ...Object.entries(DRILL_TYPE_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

export const STAGE_FILTER = [
  { value: '', label: '全部环节' },
  { value: 'plan', label: '计划阶段' },
  { value: 'execution', label: '实施阶段' },
  { value: 'review', label: '复核阶段' },
]

export const REVIEW_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(REVIEW_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]
