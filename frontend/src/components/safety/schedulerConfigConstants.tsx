// AI 配置 + 定时任务 UI 常量、格式化工具与微型展示组件
// 配色/圆角/字体全部取自 dazah-frontend/DESIGN.md tokens（Notion 风设计系统）
// 含 JSX（RunStateTag / StatusTag / ModelTypeTag），故为 .tsx

import { Tag, Tooltip } from 'antd'
import { T } from './shared-styles'
import type {
  AiConfigSource,
  AiModelConfig,
  AiModelProfile,
  SchedulerRunState,
} from '@/types/safety'

// ── 设计 tokens 复用（designtoken 唯一来源 shared-styles.T） ──
export const UI = T

export const MONO_FONT =
  'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

export const CARD_STYLE: React.CSSProperties = {
  background: UI.canvas,
  border: `1px solid ${UI.hairline}`,
  borderRadius: 12,
}

// ── 星期 ──
export const WEEK_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'] as const

export const WEEK_OPTIONS = WEEK_LABELS.map((label, value) => ({ value, label }))

/** 将 0-6（周一~周日）或 bitmask（1<<day）格式化为「每天」/「周一」/「周一~周五」/「周一、周三」 */
export function formatDow(dow?: number | null): string {
  if (dow == null) return '每天'
  // 单值：0-6 直接表示星期
  if (dow >= 0 && dow <= 6) return WEEK_LABELS[dow]
  // 兼容 bitmask：每位表示一天
  const days: number[] = []
  for (let i = 0; i < 7; i++) {
    if ((dow & (1 << i)) !== 0) days.push(i)
  }
  if (days.length === 0) return '未设置'
  if (days.length === 7) return '每天'
  return formatDaysRange(days)
}

/** 将连续星期数合并为「周一~周五」，否则用「、」连接 */
function formatDaysRange(days: number[]): string {
  const sorted = [...days].sort((a, b) => a - b)
  const groups: number[][] = []
  let start = sorted[0]
  let prev = sorted[0]
  for (let i = 1; i < sorted.length; i++) {
    const d = sorted[i]
    if (d - prev === 1) {
      prev = d
    } else {
      groups.push([start, prev])
      start = d
      prev = d
    }
  }
  groups.push([start, prev])
  return groups
    .map(([s, e]) => (s === e ? WEEK_LABELS[s] : `${WEEK_LABELS[s]}~${WEEK_LABELS[e]}`))
    .join('、')
}

const pad2 = (n: number | null | undefined) =>
  n == null ? '--' : String(n).padStart(2, '0')

/** 执行计划文案：08:00 每天 / 08:00 周一~周五 */
export function formatCronText(
  hour?: number | null,
  minute?: number | null,
  dow?: number | null,
): string {
  if (hour == null && minute == null) return '—'
  return `${pad2(hour)}:${pad2(minute)} ${formatDow(dow)}`
}

// ── 模型类型（text/vision） → 视觉映射 ──
export const MODEL_TYPE_UI: Record<string, { label: string; bg: string; text: string }> = {
  text: { label: '文本', bg: UI.sky, text: '#005bab' },
  vision: { label: '视觉', bg: UI.lavender, text: '#391c57' },
}

/** 模型类型 soft tag */
export function ModelTypeTag({ type }: { type?: string | null }) {
  if (!type) return <span style={{ color: UI.muted, fontSize: 12 }}>—</span>
  const ui = MODEL_TYPE_UI[type] ?? { label: type, bg: UI.gray, text: UI.steel }
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

// ── 启停状态 Tag ──
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

/** 今日/最近运行状态 Tag */
export function RunStateTag({ runState }: { runState?: SchedulerRunState | null }) {
  if (!runState) return <span style={{ color: UI.muted, fontSize: 12 }}>—</span>
  const { status, attempt_count, last_attempt_at } = runState
  if (status === 'success') {
    const time = last_attempt_at ? formatRunTime(last_attempt_at) : null
    return (
      <Tag color="success" style={{ borderRadius: 6, fontWeight: 600 }}>
        {time ? `成功 ${time}` : '成功'}
      </Tag>
    )
  }
  if (status === 'failed') {
    return (
      <Tooltip title={last_attempt_at ? `最后尝试：${new Date(last_attempt_at).toLocaleString('zh-CN', { hour12: false })}` : undefined}>
        <Tag color="error" style={{ borderRadius: 6, fontWeight: 600 }}>
          失败 ×{attempt_count ?? 1}
        </Tag>
      </Tooltip>
    )
  }
  return <Tag style={{ borderRadius: 6, fontWeight: 600, color: UI.steel }}>待触发</Tag>
}

function formatRunTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return ''
  }
}

// ── AI 配置卡（profile 元数据 / 字段矩阵 / 生效来源 / 动作 Tag） ──

/** 卡的字段矩阵（决定每卡渲染哪些 Form.Item；匹配 design.md §1.3） */
export type AiModelField = 'base_url' | 'model' | 'api_key' | 'dims' | 'temperature' | 'timeout'

export const AI_PROFILE_UI: Record<
  AiModelProfile,
  { label: string; color: string; hint?: string; fields: AiModelField[] }
> = {
  text: {
    label: '文本模型',
    color: '#0075de',
    fields: ['base_url', 'model', 'api_key', 'temperature', 'timeout'],
  },
  text_backup: {
    label: '文本备用模型',
    color: '#5645d4',
    hint: '主模型调用失败时自动降级',
    fields: ['base_url', 'model', 'api_key', 'timeout'],
  },
  vision: {
    label: '视觉模型',
    color: '#7b3ff2',
    fields: ['base_url', 'model', 'api_key', 'temperature', 'timeout'],
  },
  embedding: {
    label: '向量模型',
    color: '#1aae39',
    hint: '未配置时走 env 兜底；存量向量不自动重嵌入',
    fields: ['base_url', 'model', 'api_key', 'dims'],
  },
  rerank: {
    label: '重排模型',
    color: '#dd5b00',
    hint: '未配置时走 env 兜底',
    fields: ['base_url', 'model', 'api_key'],
  },
}

/** 生效来源 soft tag 映射（db/env/default/disabled/missing） */
export const AI_SOURCE_UI: Record<AiConfigSource, { label: string; bg: string; text: string }> = {
  db: { label: 'DB', bg: UI.mint, text: '#1aae39' },
  env: { label: 'ENV', bg: UI.sky, text: '#005bab' },
  default: { label: '默认', bg: UI.gray, text: UI.steel },
  disabled: { label: '已停用', bg: UI.gray, text: UI.steel },
  missing: { label: '缺失', bg: UI.gray, text: UI.steel },
}

const AI_SOURCE_TOOLTIP: Record<AiConfigSource, string> = {
  db: 'DB=数据库生效',
  env: 'ENV=环境变量兜底',
  default: '默认=代码默认值',
  disabled: '已停用=DB 行禁用，回落 env/default',
  missing: '缺失=无任何来源配置',
}

/** 「生效来源」soft tag（浅底深字、6px 圆角、12px/600，同 ModelTypeTag 范式） */
export function SourceTag({ source }: { source?: AiConfigSource | null }) {
  if (!source) return null
  const ui = AI_SOURCE_UI[source] ?? { label: source, bg: UI.gray, text: UI.steel }
  const tooltip = AI_SOURCE_TOOLTIP[source]
  const tag = (
    <span
      data-testid="ai-config-source-tag"
      title={tooltip}
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
        marginLeft: 8,
      }}
    >
      {ui.label}
    </span>
  )
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag
}

/** 后端未返回 api_key_set 时的兼容推导：api_key_masked !== '未配置' 视为已配置 */
export function isApiKeySet(
  config: Pick<AiModelConfig, 'api_key_masked' | 'api_key_set'> | null | undefined,
) {
  if (!config) return false
  return config.api_key_set ?? config.api_key_masked !== '未配置'
}

/** API Key 输入框占位：已配置 → 「已配置 · ****后4位（留空不修改）」；未配置 → 「未配置 · 填写后覆盖（留空沿用 env 兜底）」 */
export function apiKeyPlaceholder(config: AiModelConfig | null | undefined): string {
  if (isApiKeySet(config)) {
    const rest = (config?.api_key_masked ?? '').replace(/^已配置 · /, '')
    return `已配置 · ${rest || '****'}（留空不修改）`
  }
  return '未配置 · 填写后覆盖（留空沿用 env 兜底）'
}

/** 审计动作（update/enable/disable，未知原值 default） */
export const AI_AUDIT_ACTION_UI: Record<string, { label: string; color: string }> = {
  update: { label: '更新', color: 'warning' },
  enable: { label: '启用', color: 'success' },
  disable: { label: '停用', color: 'default' },
}
