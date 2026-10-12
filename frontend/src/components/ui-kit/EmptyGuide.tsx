'use client'

import { Button } from 'antd'
import type { ReactNode } from 'react'

/**
 * 引导式空态（仓储 UI 底座）：
 * 插画圆底图标 + 一句话 + 主 CTA，取代 antd 默认"暂无数据"。
 */
export function EmptyGuide({
  icon,
  title,
  description,
  actionText,
  onAction,
  extra,
  compact = false,
}: {
  icon?: ReactNode
  title: string
  description?: string
  actionText?: string
  onAction?: () => void
  /** 次级链接区（如"去物料主数据创建"文字链） */
  extra?: ReactNode
  compact?: boolean
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${compact ? 'py-6' : 'py-14'}`}
    >
      {icon && (
        <span
          aria-hidden
          className="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-surface)] [&_svg]:h-6 [&_svg]:w-6"
          style={{ color: 'var(--color-steel)' }}
        >
          {icon}
        </span>
      )}
      <div className="text-[15px] font-medium text-[var(--color-charcoal)]">{title}</div>
      {description && (
        <div className="mt-1 max-w-[420px] text-[13px] leading-5 text-[var(--color-steel)]">
          {description}
        </div>
      )}
      {actionText && onAction && (
        <Button type="primary" className="mt-4" onClick={onAction}>
          {actionText}
        </Button>
      )}
      {extra && <div className="mt-3 text-[13px] text-[var(--color-steel)]">{extra}</div>}
    </div>
  )
}
