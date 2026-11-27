import type { ReactNode } from 'react'
import dayjs from 'dayjs'

/**
 * 办理抽屉里的一个环节面板：步骤序号 + 标题 + 说明，右上角放该环节的状态标签。
 * 抽屉按阶段只渲染「当前该动手的环节」，已完成环节收进顶部步骤条里，页面始终只有一处要操作。
 */
export default function CasePanel({
  step,
  stepLabel,
  title,
  hint,
  extra,
  children,
  tone = 'default',
}: {
  /** 步骤序号（1 起），对应顶部步骤条 */
  step: number
  /** 步骤标签文字；不传显示「第 N 步」。最后一步 / 回顾类面板可以换成更直白的说法 */
  stepLabel?: string
  title: string
  hint?: ReactNode
  extra?: ReactNode
  /** 只读回顾的面板可以没有正文（如无办理权限时只给一句说明） */
  children?: ReactNode
  /** warning = 轮到 HR 动手；muted = 只读回顾 */
  tone?: 'default' | 'warning' | 'muted'
}) {
  const stepColor = tone === 'warning' ? 'text-[var(--color-warning)]' : 'text-[var(--color-steel)]'
  return (
    <section className="rounded-[var(--rounded-lg)] border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-4 space-y-3">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className={`text-[11px] font-semibold tracking-[1px] ${stepColor}`}>{stepLabel || `第 ${step} 步`}</span>
            <h3 className="m-0 text-[14px] font-medium leading-[1.4] text-[var(--color-ink)]">{title}</h3>
          </div>
          {hint && (
            <p className="m-0 mt-1 text-[13px] leading-[1.5] text-[var(--color-slate)]">{hint}</p>
          )}
        </div>
        {extra && <div className="shrink-0">{extra}</div>}
      </header>
      {children}
    </section>
  )
}

/** ISO 时间 → YYYY-MM-DD HH:mm（本地时区）。后端给的是带 +00:00 的 UTC 时间串，
 *  直接截取会差 8 小时（13:33 显示成 05:33） */
export function fmtTime(value?: string | null, fallback = '—'): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : fallback
}

export interface DaysUntil {
  days: number
  text: string
  /** 距离职日 ≤ 2 天（含已过）：清退交接应于离职日前 2 天发起，此时还没走出清退就算临期 */
  urgent: boolean
}

/** 距离职日的天数与文案。日期按本地时区解析，避免 UTC 偏移把当天算错。 */
export function daysUntil(offboardingDate: string, today = new Date()): DaysUntil {
  const [year, month, day] = offboardingDate.split('-').map(Number)
  const target = new Date(year, month - 1, day)
  const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const days = Math.round((target.getTime() - todayMidnight.getTime()) / 86_400_000)
  let text: string
  if (days > 0) text = `还有 ${days} 天`
  else if (days === 0) text = '今天'
  else text = `已过 ${-days} 天`
  return { days, text, urgent: days <= 2 }
}
