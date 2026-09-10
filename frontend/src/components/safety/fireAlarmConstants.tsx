// ═══════════════════════════════════════════════════════════════
// FireAlarm — shared constants & dynamic tag styles
// Used by: FireAlarmManagement
// 配色全部取自 dazah-frontend/DESIGN.md tokens（经 shared-styles T 导入，不本地重复定义色板）
// ═══════════════════════════════════════════════════════════════

import {
  ExperimentOutlined,
  QuestionCircleOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'

import { T } from './shared-styles'

// ── AI 维度配置（英文枚举键 → 中文标签/配色/图标；DESIGN.md §5.3）──
// 渲染时对枚举之外的值降级为灰 Tag 原文显示（见 FireAlarmManagement.DimensionTag）
export interface AiDimensionConfig {
  label: string
  bg: string
  text: string
  icon: React.ReactNode
}

export const AI_DIMENSION_CONFIG: Record<string, AiDimensionConfig> = {
  process: { label: '工艺', bg: '#dcecfa', text: '#005bab', icon: <ExperimentOutlined /> }, // tint-sky / link-blue-pressed
  operation: { label: '人员操作', bg: '#ffe8d4', text: '#793400', icon: <UserOutlined /> }, // tint-peach / brand-orange-deep
  equipment: { label: '设备设施', bg: '#e6e0f5', text: '#391c57', icon: <ToolOutlined /> }, // tint-lavender / brand-purple-800
  other: { label: '其他', bg: '#f0eeec', text: '#787671', icon: <QuestionCircleOutlined /> }, // tint-gray / steel
}

export const AI_DIMENSION_KEYS = ['process', 'operation', 'equipment', 'other']

// ── 动态 Tag 配色（报警类型/报警性质等飞书自由文本）──
// 对 name 字符码求和取模 → 6 组 DESIGN tint 对，同一名称颜色稳定。
// 特殊语义前置映射：误报置灰降噪；真实警情关键词 → error pill 风。
// 联调期按实际词表扩充 REAL_ALARM_KEYWORDS。

const TINT_PAIRS: Array<{ bg: string; text: string }> = [
  { bg: '#e6e0f5', text: '#391c57' }, // lavender / brand-purple-800
  { bg: '#ffe8d4', text: '#793400' }, // peach / brand-orange-deep
  { bg: '#d9f3e1', text: '#1aae39' }, // mint / brand-green
  { bg: '#dcecfa', text: '#005bab' }, // sky / link-blue-pressed
  { bg: '#fde0ec', text: '#a02e6d' }, // rose / brand-pink-deep
  { bg: '#f9e79f', text: '#7a5d00' }, // yellow-bold / amber-deep
]

/** 真实警情关键词（命中 → 项目 error pill 风 #e03131 on #fde0ec） */
const REAL_ALARM_KEYWORDS = ['泄漏', '真实火警', '真实报警', '冒烟', '明火', '火灾', '烟雾']

export function dynamicTagStyle(name: string): { bg: string; text: string } {
  if (!name) return { bg: T.gray, text: T.steel }
  if (name === '误报') return { bg: T.gray, text: T.steel } // 误报不是警讯，视觉降噪
  if (REAL_ALARM_KEYWORDS.some((k) => name.includes(k))) return { bg: T.rose, text: T.error }
  let hash = 0
  for (const ch of name) hash = (hash + (ch.codePointAt(0) ?? 0)) % 100000
  return TINT_PAIRS[hash % TINT_PAIRS.length]
}

// ── 推送结果文案（报告 Modal 推送 Tag）──
export const PUSH_RESULT: Record<'success' | 'skipped' | 'failed', { label: string; color: string }> = {
  success: { label: '推送成功', color: 'green' },
  skipped: { label: '未配置·已跳过', color: 'default' },
  failed: { label: '推送失败', color: 'red' },
}
