'use client'

import type { ReactNode } from 'react'
import { StatusTag } from './StatusTag'
import type { Tone } from './tokens'

/**
 * 信息流分组与可点击行项（ui-kit）：
 * FeedGroup=小节标题+行列表；FeedRow=一行（标签 pill+标题+右侧数据），
 * hover 强调、可点击下钻。驾驶舱右栏"速递/待办"类窄列信息流用它。
 */
export function FeedRow({
  title,
  right,
  tag,
  tagLabel,
  onClick,
}: {
  title: ReactNode
  right?: ReactNode
  tag?: Tone
  /** tag 的 pill 文案；缺省时只渲染色点 */
  tagLabel?: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className="flex w-full items-center gap-2 rounded-lg border-0 bg-transparent px-2 py-2 text-left transition-colors hover:bg-[var(--color-surface)] disabled:cursor-default"
    >
      {tag && <StatusTag tone={tag} label={tagLabel ?? ''} />}
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--color-charcoal)]">{title}</span>
      {right && (
        <span className="shrink-0 text-[12px] tabular-nums text-[var(--color-steel)]">{right}</span>
      )}
    </button>
  )
}

export function FeedGroup({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1 px-2 text-[12px] font-medium uppercase tracking-wide text-[var(--color-stone)]">
        {title}
      </div>
      <div className="-mx-1 flex flex-col">{children}</div>
    </div>
  )
}
