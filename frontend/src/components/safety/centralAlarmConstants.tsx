// ═══════════════════════════════════════════════════════════════
// CentralAlarm — shared constants & dynamic tag styles
// Used by: CentralAlarmManagement
// 配色全部取自 dazah-frontend/DESIGN.md tokens（经 shared-styles T 导入，不本地重复定义色板）
// ═══════════════════════════════════════════════════════════════

import {
  ExperimentOutlined,
  QuestionCircleOutlined,
  ToolOutlined,
  UserOutlined,
  WarningOutlined,
  RedoOutlined,
  InfoCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'

import { T } from './shared-styles'

// ── AI 异常模式配置（英文枚举键 → 中文标签/配色/图标；DESIGN.md）──
export interface AiPatternConfig {
  label: string
  bg: string
  text: string
  icon: React.ReactNode
}

export const AI_PATTERN_CONFIG: Record<string, AiPatternConfig> = {
  normal_transient: { label: '正常瞬报', bg: '#d9f3e1', text: '#1aae39', icon: <InfoCircleOutlined /> }, // mint / green
  repeated: { label: '重复报警', bg: '#ffe8d4', text: '#793400', icon: <RedoOutlined /> }, // peach / orange-deep
  false_alarm: { label: '误报', bg: '#f0eeec', text: '#787671', icon: <WarningOutlined /> }, // gray / steel
  anomalous: { label: '异常依赖', bg: '#fde0ec', text: '#a02e6d', icon: <ExclamationCircleOutlined /> }, // rose / pink-deep
}

export const AI_PATTERN_KEYS = ['normal_transient', 'repeated', 'false_alarm', 'anomalous']

// ── AI 维度配置（英文枚举键 → 中文标签/配色/图标；DESIGN.md）──
export interface AiDimensionConfig {
  label: string
  bg: string
  text: string
  icon: React.ReactNode
}

export const AI_DIMENSION_CONFIG: Record<string, AiDimensionConfig> = {
  process: { label: '工艺', bg: '#dcecfa', text: '#005bab', icon: <ExperimentOutlined /> },
  operation: { label: '人员操作', bg: '#ffe8d4', text: '#793400', icon: <UserOutlined /> },
  equipment: { label: '设备设施', bg: '#e6e0f5', text: '#391c57', icon: <ToolOutlined /> },
  other: { label: '其他', bg: '#f0eeec', text: '#787671', icon: <QuestionCircleOutlined /> },
}

export const AI_DIMENSION_KEYS = ['process', 'operation', 'equipment', 'other']

// ── 动态 Tag 配色（报警类型/岗位等自由文本）──
const TINT_PAIRS: Array<{ bg: string; text: string }> = [
  { bg: '#e6e0f5', text: '#391c57' },
  { bg: '#ffe8d4', text: '#793400' },
  { bg: '#d9f3e1', text: '#1aae39' },
  { bg: '#dcecfa', text: '#005bab' },
  { bg: '#fde0ec', text: '#a02e6d' },
  { bg: '#f9e79f', text: '#7a5d00' },
]

export function dynamicTagStyle(name: string): { bg: string; text: string } {
  if (!name) return { bg: T.gray, text: T.steel }
  if (name === '误报') return { bg: T.gray, text: T.steel }
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
