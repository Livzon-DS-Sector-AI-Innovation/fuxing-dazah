'use client'

import type { ReactNode } from 'react'
import { TONE_STYLE, type Tone } from './tokens'

/**
 * 语义状态点标（仓储 UI 底座）：
 * 小圆点 + 文案的轻量 pill，用于库存状态/单据状态/对账状态等所有状态表达。
 * 比 antd Tag 更轻，色板全局唯一（tokens.ts）。
 */
export function StatusTag({
  tone = 'default',
  label,
  icon,
  bordered = false,
}: {
  tone?: Tone
  label: ReactNode
  icon?: ReactNode
  bordered?: boolean
}) {
  const style = TONE_STYLE[tone]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] leading-[18px]"
      style={{
        background: style.bg,
        color: style.color,
        fontWeight: 500,
        ...(bordered ? { border: `1px solid ${style.color}33` } : {}),
      }}
    >
      {icon ?? <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: style.color }} />}
      {label}
    </span>
  )
}
