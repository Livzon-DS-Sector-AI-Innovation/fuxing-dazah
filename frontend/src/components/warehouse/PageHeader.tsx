import type { ReactNode } from 'react'

/**
 * 页面页头（仓储 UI 底座）：
 * 标题 + 描述 + 右侧主操作区（一页一主按钮），底部统一分隔留白。
 * 兼容旧 API（extra），新代码统一用 actions 命名。
 */
export function PageHeader({
  title,
  description,
  extra,
  actions,
  breadcrumb,
}: {
  title: string
  description?: string
  /** 旧参数名，等同 actions */
  extra?: ReactNode
  /** 右侧操作区：主按钮唯一，其余用次级/图标按钮 */
  actions?: ReactNode
  /** 面包屑（可选），如 ['仓储管理', '库存管理'] */
  breadcrumb?: string[]
}) {
  const actionArea = actions ?? extra
  return (
    <div
      className="mb-4 flex flex-wrap items-start justify-between gap-3 pb-3"
      style={{ borderBottom: '1px solid var(--color-hairline-soft)' }}
    >
      <div className="min-w-0">
        {breadcrumb && breadcrumb.length > 0 && (
          <nav aria-label="面包屑" className="mb-1 text-[12px] leading-4 text-[var(--color-stone)]">
            {breadcrumb.map((item, i) => (
              <span key={i}>
                {i > 0 && <span className="mx-1.5">/</span>}
                {item}
              </span>
            ))}
          </nav>
        )}
        <h1 className="mb-0.5 text-[20px] font-semibold leading-7 text-[var(--color-charcoal)]">{title}</h1>
        {description && <p className="mb-0 text-[13px] leading-5 text-[var(--color-steel)]">{description}</p>}
      </div>
      {actionArea && <div className="flex shrink-0 items-center gap-2">{actionArea}</div>}
    </div>
  )
}
