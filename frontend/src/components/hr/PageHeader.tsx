import type { ReactNode } from 'react'

// HR 页面统一页头（此前 17+ 页各自手写 h1+描述，样式渐行渐远）。
// server / client 组件均可使用；标题行右侧动作经 actions 传入。
interface PageHeaderProps {
  title: string
  description?: string
  /** 标题行右侧动作区（按钮等） */
  actions?: ReactNode
}

export default function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] leading-tight">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-[14px] text-[var(--color-steel)]">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 ml-auto">{actions}</div>}
    </div>
  )
}
