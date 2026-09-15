import type { ReactNode } from 'react'

/**
 * 页面页头（仓储 V2.0 三件套之一）：
 * 标题 + 描述 + 右侧操作区，统一台账/看板页的头部结构。
 */
export function PageHeader({
  title,
  description,
  extra,
}: {
  title: string
  description?: string
  extra?: ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 16,
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">{title}</h1>
        {description && <p className="text-[14px] text-[var(--color-steel)]">{description}</p>}
      </div>
      {extra && <div>{extra}</div>}
    </div>
  )
}
