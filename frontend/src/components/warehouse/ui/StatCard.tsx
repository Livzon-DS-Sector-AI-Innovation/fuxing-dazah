'use client'

import { Skeleton } from 'antd'
import type { ReactNode } from 'react'
import { TONE_STYLE, type Tone } from './tokens'

/**
 * 统计卡（仓储 UI 底座）：
 * 图标 chip（tone 语义色 10% 底）+ 标签 + 大数字（等宽）+ 右侧 delta/说明。
 * emphasized=首屏主卡（数字更大）；onClick=可下钻（hover 抬升）。
 */
export function StatCard({
  label,
  value,
  sub,
  icon,
  tone = 'default',
  emphasized = false,
  onClick,
  loading = false,
}: {
  label: string
  value: ReactNode
  /** 数字右侧/下方的补充：环比 delta、单位说明等 */
  sub?: ReactNode
  icon?: ReactNode
  tone?: Tone
  emphasized?: boolean
  onClick?: () => void
  loading?: boolean
}) {
  const toneStyle = TONE_STYLE[tone]
  const interactive = Boolean(onClick)
  return (
    <div
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? e => {
              if (e.key === 'Enter' || e.key === ' ') onClick?.()
            }
          : undefined
      }
      className="rounded-xl border border-[var(--color-hairline)] bg-white px-5 py-4 transition-shadow"
      style={{
        boxShadow: '0 1px 2px rgba(16,24,40,0.04)',
        cursor: interactive ? 'pointer' : undefined,
      }}
      {...(interactive
        ? {
            onMouseEnter: e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(16,24,40,0.08)'),
            onMouseLeave: e => (e.currentTarget.style.boxShadow = '0 1px 2px rgba(16,24,40,0.04)'),
          }
        : {})}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 1 }} title={false} />
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13px] leading-5 text-[var(--color-steel)]">{label}</div>
            <div
              className={`mt-1 font-semibold tabular-nums leading-7 text-[var(--color-charcoal)] ${
                emphasized ? 'text-[28px]' : 'text-[22px]'
              }`}
            >
              {value}
            </div>
            {sub && <div className="mt-0.5 text-[12px] leading-5 text-[var(--color-steel)]">{sub}</div>}
          </div>
          {icon && (
            <span
              aria-hidden
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg [&_svg]:h-[18px] [&_svg]:w-[18px]"
              style={{ background: toneStyle.bg, color: toneStyle.color }}
            >
              {icon}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

/** 环比 delta 展示：升红降绿的可选反转（出入库场景升=红） */
export function StatDelta({ value, suffix, invert = false }: { value: number; suffix?: string; invert?: boolean }) {
  if (!Number.isFinite(value) || value === 0) {
    return <span>— 持平</span>
  }
  const up = value > 0
  const good = invert ? !up : up
  return (
    <span style={{ color: good ? 'var(--wh-ok)' : 'var(--wh-danger)', fontWeight: 500 }}>
      {up ? '↑' : '↓'} {Math.abs(value)}
      {suffix}
    </span>
  )
}
