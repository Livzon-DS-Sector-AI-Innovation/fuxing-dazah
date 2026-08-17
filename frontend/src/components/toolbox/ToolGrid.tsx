'use client'

// 工具箱首页：卡片网格。工具图片缺失时回退首字色块。

import Link from 'next/link'

import type { ToolInfo } from '@/types/toolbox'

const TINTS = [
  '#ffe8d4', // card-tint-peach
  '#fde0ec', // card-tint-rose
  '#d9f3e1', // card-tint-mint
  '#e6e0f5', // card-tint-lavender
  '#dcecfa', // card-tint-sky
  '#fef7d6', // card-tint-yellow
  '#f8f5e8', // card-tint-cream
]

export function ToolGrid({ tools }: { tools: ToolInfo[] }) {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-6">
      {tools.map((tool, i) => (
        <Link
          key={tool.id}
          href={`/toolbox/${tool.id}`}
          className="group block rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-5 transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-4">
            {tool.image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`${apiBase}${tool.image}`}
                alt={tool.name}
                className="h-14 w-14 rounded-full object-cover border border-[var(--color-hairline-soft)]"
              />
            ) : (
              <div
                className="flex h-14 w-14 items-center justify-center rounded-full text-xl font-semibold text-[var(--color-charcoal)]"
                style={{ background: TINTS[i % TINTS.length] }}
              >
                {tool.name.slice(0, 1)}
              </div>
            )}
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold text-[var(--color-charcoal)] group-hover:text-[var(--color-primary)] transition-colors">
                {tool.name}
              </h3>
              <p className="mt-1 text-[13px] leading-snug text-[var(--color-slate)] line-clamp-2">
                {tool.description}
              </p>
            </div>
          </div>
        </Link>
      ))}
    </div>
  )
}
