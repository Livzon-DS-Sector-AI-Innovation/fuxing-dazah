'use client'

import type { CSSProperties, ReactNode } from 'react'
import dayjs from 'dayjs'
import {
  CAPA_SEVERITY_LABEL,
  CAPA_STATUS_LABEL,
  DEVIATION_CLASSIFICATION_LABEL,
  DEVIATION_STATUS_LABEL,
  type CapaSeverity,
  type CapaStatus,
  type DeviationClassification,
  type DeviationStatus,
} from '@/types/qa-deviation'

// DESIGN.md：状态 pill 用语义色 + 对应 pastel tint，按钮 8px/卡片 12px 圆角。
export const pill = (color: string, bg: string): CSSProperties => ({
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
  whiteSpace: 'nowrap',
})

export const PILL = {
  success: pill('#1aae39', '#d9f3e1'),
  warning: pill('#dd5b00', '#ffe8d4'),
  error: pill('#e03131', '#fde0ec'),
  info: pill('#0075de', '#dcecfa'),
  purple: pill('#5645d4', '#e6e0f5'),
  neutral: pill('#5d5b54', '#f0eeec'),
  muted: pill('#a4a097', '#f0eeec'),
}

export const cardStyle: CSSProperties = { borderRadius: 12, border: '1px solid #e5e3df' }
/** 卡片头与内容使用同一内边距，右上角按钮才有上下呼吸空间且与正文左对齐。 */
export const cardStyles: { header: CSSProperties; body: CSSProperties } = {
  header: { padding: '8px 20px', minHeight: 52 },
  body: { padding: 20 },
}
export const subtleText: CSSProperties = { color: '#787671', fontSize: 12 }
export const tabularNums: CSSProperties = { fontVariantNumeric: 'tabular-nums' }

/** 台账/详情共用的空状态：说明发生了什么，并给出下一步动作。 */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div style={{ padding: '28px 16px', textAlign: 'center' }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#37352f' }}>{title}</div>
      {hint && <div style={{ marginTop: 4, fontSize: 13, color: '#787671' }}>{hint}</div>}
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  )
}

const DEVIATION_STATUS_PILL: Record<DeviationStatus, CSSProperties> = {
  draft: PILL.neutral,
  investigating: PILL.info,
  assessing: PILL.warning,
  closed: PILL.success,
}

const CLASSIFICATION_PILL: Record<DeviationClassification, CSSProperties> = {
  minor: PILL.success,
  moderate: PILL.warning,
  critical: PILL.error,
}

const CAPA_STATUS_PILL: Record<CapaStatus, CSSProperties> = {
  planned: PILL.neutral,
  in_progress: PILL.info,
  completed: PILL.purple,
  effect_evaluating: PILL.warning,
  closed: PILL.success,
}

const SEVERITY_PILL: Record<CapaSeverity, CSSProperties> = {
  minor: PILL.success,
  major: PILL.warning,
  critical: PILL.error,
}

export function DeviationStatusPill({ status }: { status: DeviationStatus }) {
  return <span style={DEVIATION_STATUS_PILL[status]}>{DEVIATION_STATUS_LABEL[status]}</span>
}

export function ClassificationPill({ value }: { value: DeviationClassification | null }) {
  if (!value) return <span style={subtleText}>未定级</span>
  return <span style={CLASSIFICATION_PILL[value]}>{DEVIATION_CLASSIFICATION_LABEL[value]}</span>
}

export function CapaStatusPill({ status }: { status: CapaStatus }) {
  return <span style={CAPA_STATUS_PILL[status]}>{CAPA_STATUS_LABEL[status]}</span>
}

export function SeverityPill({ value }: { value: CapaSeverity }) {
  return <span style={SEVERITY_PILL[value]}>{CAPA_SEVERITY_LABEL[value]}</span>
}

/** 关闭期限：日期在上、剩余天数在下，按紧迫度着色（≤7 天橙、超期红）。 */
export function DueDateCell({
  dueDate,
  daysRemaining,
  isOverdue,
  closed,
}: {
  dueDate: string
  daysRemaining: number | null
  isOverdue: boolean
  closed: boolean
}) {
  if (closed || daysRemaining === null) return <span style={tabularNums}>{fmtDate(dueDate)}</span>
  const color = isOverdue ? '#e03131' : daysRemaining <= 7 ? '#dd5b00' : '#787671'
  const hint = isOverdue ? `超期 ${Math.abs(daysRemaining)} 天` : `剩 ${daysRemaining} 天`
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
      <span style={tabularNums}>{fmtDate(dueDate)}</span>
      <span style={{ fontSize: 12, color, fontWeight: isOverdue ? 600 : 500 }}>{hint}</span>
    </span>
  )
}

export function fmtDate(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—'
}

export function fmtDateTime(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'
}

export function fmtBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function toOptions<T extends string>(labels: Record<T, string>): { value: T; label: string }[] {
  return (Object.keys(labels) as T[]).map((value) => ({ value, label: labels[value] }))
}

export function actionError(result: { success: boolean; error?: string }): string {
  return (!result.success && result.error) || '操作失败'
}

/** 只读字段块：标签在上、值在下，空值用占位符而不是空白。 */
export function Field({ label, children, span = 1 }: { label: ReactNode; children: ReactNode; span?: 1 | 2 | 3 }) {
  const empty = children === null || children === undefined || children === ''
  return (
    <div style={{ gridColumn: `span ${span}` }}>
      <div style={{ fontSize: 12, color: '#787671', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 14, color: empty ? '#a4a097' : '#1a1a1a', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {empty ? '未填写' : children}
      </div>
    </div>
  )
}

export const fieldGrid = (columns: number): CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
  gap: '12px 20px',
})
