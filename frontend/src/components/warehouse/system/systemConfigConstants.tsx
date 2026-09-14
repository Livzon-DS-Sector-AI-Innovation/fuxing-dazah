'use client'

// 仓库系统配置中心 UI 常量与微型展示组件（对齐 safety/schedulerConfigConstants 范式）
// 配色取自 dazah-frontend/DESIGN.md tokens（Notion 风设计系统，与 safety shared-styles.T 同源）
// 含 JSX（SourceTag / StatusTag），故为 .tsx

import { Tag, Tooltip } from 'antd'

import type {
  WarehouseConfigSource,
  WarehouseProfileStatus,
  WarehouseSchedule,
} from '@/types/warehouse'

// ── 设计 tokens ──
export const UI = {
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
  error: '#E03131',
  warning: '#DD5B00',
  success: '#1AAE39',
  mint: '#d9f3e1',
  lavender: '#e6e0f5',
  sky: '#dcecfa',
  gray: '#f0eeec',
  roseTint: '#fde0ec',
} as const

export const MONO_FONT =
  'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

export const CARD_STYLE: React.CSSProperties = {
  background: UI.canvas,
  border: `1px solid ${UI.hairline}`,
  borderRadius: 12,
}

// ── 模型位 UI（profile → 标题/色点/字段矩阵）──

export type WarehouseModelField =
  | 'base_url'
  | 'model'
  | 'api_key'
  | 'temperature'
  | 'max_tokens'
  | 'timeout'

/** 字段矩阵以后端 ai_config/registry.py 的 field_names 为准：
 *  agent 全字段；agent_backup 无 temperature/max_tokens（写入 422） */
export const WAREHOUSE_PROFILE_UI: Record<
  string,
  { label: string; color: string; hint?: string; fields: WarehouseModelField[] }
> = {
  agent: {
    label: 'Agent 主模型',
    color: '#0075de',
    hint: '仓库助手对话与送货单视觉识别（tool-calling + vision 单模型位）',
    fields: ['base_url', 'model', 'api_key', 'temperature', 'max_tokens', 'timeout'],
  },
  agent_backup: {
    label: 'Agent 备用',
    color: '#5645d4',
    hint: '主模型调用失败（401/429/5xx/超时）时自动降级；未配置则无降级',
    fields: ['base_url', 'model', 'api_key', 'timeout'],
  },
}

// ── 来源 / 状态 soft tag ──

export const SOURCE_UI: Record<string, { label: string; bg: string; text: string }> = {
  db: { label: 'DB', bg: UI.mint, text: '#1aae39' },
  env: { label: 'ENV', bg: UI.sky, text: '#005bab' },
  default: { label: '默认', bg: UI.gray, text: UI.steel },
  disabled: { label: '已停用', bg: UI.gray, text: UI.steel },
  missing: { label: '缺失', bg: UI.gray, text: UI.steel },
}

const SOURCE_TOOLTIP: Record<string, string> = {
  db: 'DB=数据库生效',
  env: 'ENV=环境变量兜底',
  default: '默认=代码默认值',
  disabled: '已停用=DB 行禁用，回落 env/default',
  missing: '缺失=无任何来源配置',
}

/** 生效来源 soft tag（浅底深字、6px 圆角、12px/600） */
export function SourceTag({
  source,
  withMargin = true,
}: {
  source?: WarehouseConfigSource | WarehouseProfileStatus | string | null
  withMargin?: boolean
}) {
  if (!source) return null
  const ui = SOURCE_UI[source] ?? { label: source, bg: UI.gray, text: UI.steel }
  const tooltip = SOURCE_TOOLTIP[source]
  const tag = (
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
        marginLeft: withMargin ? 8 : 0,
      }}
    >
      {ui.label}
    </span>
  )
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag
}

/** 字段级来源小字（DB/ENV/默认） */
export function FieldSource({ source }: { source?: WarehouseConfigSource | null }) {
  if (!source) return null
  const ui = SOURCE_UI[source] ?? { label: source, bg: UI.gray, text: UI.steel }
  return (
    <Tooltip title={SOURCE_TOOLTIP[source]}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: ui.text,
          background: ui.bg,
          borderRadius: 4,
          padding: '0 4px',
          lineHeight: '16px',
          marginLeft: 6,
          flexShrink: 0,
        }}
      >
        {ui.label}
      </span>
    </Tooltip>
  )
}

/** 启停状态 Tag */
export function StatusTag({ enabled }: { enabled: boolean }) {
  return enabled ? (
    <Tag color="success" style={{ borderRadius: 6, fontWeight: 600 }}>
      启用
    </Tag>
  ) : (
    <Tag style={{ borderRadius: 6, fontWeight: 600, color: UI.muted, borderColor: UI.hairline }}>
      停用
    </Tag>
  )
}

// ── 文案与格式化 ──

export const SAVE_OK_MESSAGE = '配置已保存，实时生效'

/** 后端未返回 api_key_set 时的兼容推导：mask ≠ '未配置' 视为已配置 */
export function isApiKeySet(masked: string | null | undefined): boolean {
  return !!masked && masked !== '未配置'
}

/** API Key 输入框占位：已配置 → 「已配置 · ****后4位（留空不修改）」 */
export function apiKeyPlaceholder(masked: string | null | undefined): string {
  if (isApiKeySet(masked)) {
    const rest = (masked ?? '').replace(/^已配置 · /, '')
    return `已配置 · ${rest || '****'}（留空不修改）`
  }
  return '未配置 · 填写后覆盖（留空沿用 env 兜底）'
}

/** Bitable base_token 输入框占位（脱敏值直接来自后端：****后4位 / 未配置） */
export function bitableTokenPlaceholder(masked: string): string {
  return masked === '未配置' ? '未配置 · 填写后覆盖' : `当前 ${masked}（留空提交 = 清空覆盖）`
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 10000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export function formatNumber(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString()
}

/** schedule → 展示文案：每 300 秒 / cron: ... / 事件触发 / — */
export function formatSchedule(schedule: WarehouseSchedule): string {
  if (!schedule) return '事件触发'
  if (schedule.type === 'interval') return `每 ${schedule.seconds} 秒`
  return `cron: ${schedule.expr}`
}

// ── 场景 / 审计 ──

export const WAREHOUSE_SCENARIO_LABELS: Record<string, string> = {
  agent_chat: '仓库助手对话',
  receipt_recognition: '送货单识别入库',
}

export function scenarioLabel(scenario: string | null | undefined): string {
  if (!scenario) return '—'
  return WAREHOUSE_SCENARIO_LABELS[scenario] ?? scenario
}

/** 审计动作（update/enable/disable） */
export const AUDIT_ACTION_UI: Record<string, { label: string; color: string }> = {
  update: { label: '更新', color: 'warning' },
  enable: { label: '启用', color: 'success' },
  disable: { label: '停用', color: 'default' },
}
