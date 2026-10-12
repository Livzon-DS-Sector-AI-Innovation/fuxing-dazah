'use client'

import type { ReactNode } from 'react'

/**
 * 区块卡（仓储 UI 底座）：
 * 标题 + 说明 + 右上动作 + 内容，统一卡片圆角/阴影/内边距。
 * 比裸 antd Card 多了说明行与统一的头部排版。
 */
export function SectionCard({
  title,
  description,
  action,
  children,
  className = '',
  bodyClassName = '',
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={`rounded-xl border border-[var(--color-hairline)] bg-white ${className}`}
      style={{ boxShadow: '0 1px 2px rgba(16,24,40,0.04)' }}
    >
      <header className="flex items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold leading-6 text-[var(--color-charcoal)]">{title}</h3>
          {description && (
            <p className="mt-0.5 text-[12px] leading-5 text-[var(--color-steel)]">{description}</p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      <div className={`px-5 pb-5 pt-3 ${bodyClassName}`}>{children}</div>
    </section>
  )
}
