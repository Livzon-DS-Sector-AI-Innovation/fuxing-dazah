'use client'

// 工具箱首页：工具卡片网格。
// 卡片签名元素为「步骤轨道」——每个工具本质是分步流程，卡片底部一条节点轨道
// 展示步骤数，节点用工具专属 pastel tint 的深色版本。

import Link from 'next/link'
import { SettingOutlined } from '@ant-design/icons'

import type { ToolInfo } from '@/types/toolbox'
import { toolTint } from './toolTint'

/** 步骤轨道：count 个节点由细线串联，节点用工具识别色填充。 */
function StepRail({ count, ink }: { count: number; ink: string }) {
  if (count === 0) return null
  return (
    <span className="flex items-center gap-1" aria-label={`${count} 个步骤`}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span className="h-px w-3 bg-[var(--color-hairline-strong)]" />}
          <span className="h-2 w-2 rounded-full" style={{ background: ink }} />
        </span>
      ))}
    </span>
  )
}

export function ToolGrid({ tools }: { tools: ToolInfo[] }) {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  return (
    <div className="px-6 pb-6">
      <p className="mt-1 text-[13px] text-[var(--color-slate)]">
        上传原始记录，按步骤执行核对、汇总与写入。每个工具由若干步骤组成，按顺序完成即可。
      </p>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {tools.map((tool) => {
          const { bg, ink } = toolTint(tool.id)
          return (
            <Link
              key={tool.id}
              href={`/toolbox/${tool.id}`}
              className="group block rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-5 transition-shadow hover:shadow-[rgba(15,15,15,0.04)_0px_1px_2px_0px,rgba(15,15,15,0.08)_0px_4px_12px_0px]"
            >
              <div className="flex items-center gap-4">
                {tool.image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`${apiBase}${tool.image}`}
                    alt={tool.name}
                    className="h-12 w-12 rounded-xl object-cover border border-[var(--color-hairline-soft)]"
                  />
                ) : (
                  <div
                    className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-lg font-semibold"
                    style={{ background: bg, color: ink }}
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
              <div className="mt-4 flex items-center justify-between border-t border-[var(--color-hairline-soft)] pt-3">
                <span className="flex items-center gap-2">
                  <StepRail count={tool.steps.length} ink={ink} />
                  <span className="text-[12px] text-[var(--color-steel)]">{tool.steps.length} 步</span>
                </span>
                {tool.config_schema.length > 0 && (
                  <span className="inline-flex items-center gap-1 text-[12px] text-[var(--color-steel)]">
                    <SettingOutlined />
                    可配置
                  </span>
                )}
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
