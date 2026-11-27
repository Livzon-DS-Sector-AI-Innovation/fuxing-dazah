'use client'

import type { CSSProperties } from 'react'
import { Checkbox, Tooltip, Typography } from 'antd'
import dayjs from 'dayjs'
import { moduleMenus, type SubMenuItem } from '@/lib/menu-config'
import { FEEDBACK_TYPE_LABELS, type Feedback, type FeedbackType } from '@/types/feedback'

/** DESIGN.md 状态 pill：语义色 + 对应 pastel tint，12px/600、4px 圆角。 */
const pill = (color: string, bg: string): CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 10px',
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  lineHeight: '20px',
  color,
  background: bg,
  whiteSpace: 'nowrap',
})

const TYPE_PILL: Record<FeedbackType, CSSProperties> = {
  bug: pill('#e03131', '#fde0ec'),
  ux: pill('#0075de', '#dcecfa'),
  feature: pill('#1aae39', '#d9f3e1'),
}

const STATUS_PILL = {
  pending: pill('#5d5b54', '#f0eeec'),
  handled: pill('#1aae39', '#d9f3e1'),
}

/** 菜单路径 → 业务页面名；找不到时回退原始路径。 */
const PAGE_LABELS = (() => {
  const entries: { path: string; label: string }[] = []
  const walk = (items: SubMenuItem[]) => {
    for (const item of items) {
      if (item.children?.length) walk(item.children)
      else if (item.path) entries.push({ path: item.path, label: item.label })
    }
  }
  for (const mod of moduleMenus) {
    if (mod.path) entries.push({ path: mod.path, label: mod.label })
    walk(mod.children)
  }
  return entries.sort((a, b) => b.path.length - a.path.length)
})()

function resolvePageLabel(path: string): string {
  const hit = PAGE_LABELS.find((e) => path === e.path || path.startsWith(`${e.path}/`))
  return hit?.label ?? path
}

export function FeedbackTypeTag({ type }: { type: FeedbackType }) {
  return <span style={TYPE_PILL[type]}>{FEEDBACK_TYPE_LABELS[type]}</span>
}

/** 只读状态（我的反馈）；已处理时悬停显示处理人与时间。 */
export function FeedbackStatusTag({ feedback }: { feedback: Feedback }) {
  if (!feedback.is_handled) return <span style={STATUS_PILL.pending}>待处理</span>
  const who = feedback.handled_by_name ?? '管理员'
  const when = feedback.handled_at ? dayjs(feedback.handled_at).format('MM-DD HH:mm') : ''
  return (
    <Tooltip title={`${who} ${when}`.trim()}>
      <span style={STATUS_PILL.handled}>已处理</span>
    </Tooltip>
  )
}

/** 管理端：状态本身就是处理开关，省掉独立操作列。 */
export function FeedbackHandledToggle({
  feedback,
  loading,
  onToggle,
}: {
  feedback: Feedback
  loading: boolean
  onToggle: () => void
}) {
  const handledNote = [feedback.handled_by_name, feedback.handled_at ? dayjs(feedback.handled_at).format('MM-DD HH:mm') : '']
    .filter(Boolean)
    .join(' ')
  return (
    <Tooltip
      title={
        feedback.is_handled
          ? `${handledNote ? `${handledNote}，` : ''}点击取消标记`
          : '点击标记为已处理'
      }
    >
      <Checkbox checked={feedback.is_handled} disabled={loading} onChange={() => onToggle()}>
        <span
          className={
            feedback.is_handled ? 'text-[var(--color-success)]' : 'text-[var(--color-slate)]'
          }
        >
          {feedback.is_handled ? '已处理' : '待处理'}
        </span>
      </Checkbox>
    </Tooltip>
  )
}

export function FeedbackContentCell({ content }: { content: string }) {
  return (
    <Typography.Paragraph
      ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
      style={{ marginBottom: 0, lineHeight: 1.55 }}
    >
      {content}
    </Typography.Paragraph>
  )
}

/** 内容下方的来源行：提交人 / 部门 / 页面 / 时间，统一 12px 弱化。 */
export function FeedbackMeta({
  feedback,
  showSubmitter = true,
}: {
  feedback: Feedback
  showSubmitter?: boolean
}) {
  const when = feedback.created_at ? dayjs(feedback.created_at) : null
  const timeLabel = when
    ? when.year() === dayjs().year()
      ? when.format('MM-DD HH:mm')
      : when.format('YYYY-MM-DD HH:mm')
    : '—'
  return (
    <div className="mt-1 flex min-w-0 items-center gap-2 whitespace-nowrap text-[12px] text-[var(--color-stone)]">
      {showSubmitter && (
        <span className="shrink-0 font-medium text-[var(--color-slate)]">
          {feedback.submitter_name}
        </span>
      )}
      {showSubmitter && feedback.submitter_department && (
        <span className="min-w-0 truncate">{feedback.submitter_department}</span>
      )}
      {feedback.page_path && (
        <Tooltip title={feedback.page_path}>
          <span className="min-w-0 truncate">{resolvePageLabel(feedback.page_path)}</span>
        </Tooltip>
      )}
      <Tooltip title={when?.format('YYYY-MM-DD HH:mm:ss')}>
        <span className="shrink-0 tabular-nums">{timeLabel}</span>
      </Tooltip>
    </div>
  )
}
