'use client'

// 工具箱首页：工具卡片网格。
// 卡片签名元素为「步骤轨道」——每个工具本质是分步流程，卡片底部一条节点轨道
// 展示步骤数，节点用工具专属 pastel tint 的深色版本。
// 无使用权限的工具卡片置灰可点，点击提示无权限（执行接口另有 403 兜底）。

import Link from 'next/link'
import { App } from 'antd'
import { LockOutlined, SettingOutlined } from '@ant-design/icons'

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

/** 卡片主体（可点击/置灰两种外壳共用）。muted 时用灰阶弱化，保持不透明度（不透背景）但呈禁用态。 */
function ToolCardBody({ tool, apiBase, muted = false }: { tool: ToolInfo; apiBase: string; muted?: boolean }) {
  const { bg, ink } = toolTint(tool.id)
  return (
    <>
      <div className="flex items-center gap-4">
        {tool.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${apiBase}${tool.image}`}
            alt={tool.name}
            className="h-12 w-12 rounded-xl object-cover border border-[var(--color-hairline-soft)]"
            style={muted ? { filter: 'grayscale(1) opacity(0.7)' } : undefined}
          />
        ) : (
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-lg font-semibold"
            style={muted ? { background: 'var(--color-surface-soft)', color: 'var(--color-muted)' } : { background: bg, color: ink }}
          >
            {tool.name.slice(0, 1)}
          </div>
        )}
        <div className="min-w-0">
          <h3
            className={`text-[15px] font-semibold ${
              muted
                ? 'text-[var(--color-muted)]'
                : 'text-[var(--color-charcoal)] group-hover:text-[var(--color-primary)] transition-colors'
            }`}
          >
            {tool.name}
          </h3>
          <p
            className={`mt-1 text-[13px] leading-snug line-clamp-2 ${
              muted ? 'text-[var(--color-steel)]' : 'text-[var(--color-slate)]'
            }`}
          >
            {tool.description}
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-[var(--color-hairline-soft)] pt-3">
        <span className="flex items-center gap-2">
          <StepRail count={tool.steps.length} ink={ink} />
          <span className={`text-[12px] ${muted ? 'text-[var(--color-stone)]' : 'text-[var(--color-steel)]'}`}>
            {tool.steps.length} 步
          </span>
        </span>
        {tool.config_schema.length > 0 && tool.can_config && (
          <span className={`inline-flex items-center gap-1 text-[12px] ${muted ? 'text-[var(--color-stone)]' : 'text-[var(--color-steel)]'}`}>
            <SettingOutlined />
            可配置
          </span>
        )}
      </div>
    </>
  )
}

export function ToolGrid({ tools }: { tools: ToolInfo[] }) {
  const { message } = App.useApp()
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  return (
    <div className="px-6 pb-6 pointer-events-none">
      <p className="mt-1 text-[13px] text-[var(--color-slate)]">
        金漆描龙凤，朱砂点牡丹。
      </p>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pointer-events-none">
        {tools.map((tool) => {
          if (tool.can_use) {
            return (
              <Link
                key={tool.id}
                href={`/toolbox/${tool.id}`}
                // antd 的全局 reset 会覆盖 <a> 的背景（unlayered 优先于 Tailwind @layer utilities），
                // 因此用内联样式设半透明白，配合 backdrop-blur-md 呈现毛玻璃；背景丝线会被柔化透出。
                style={{ backgroundColor: 'rgba(255, 255, 255, 0.4)' }}
                className="group block rounded-xl border border-[var(--color-hairline)] p-5 backdrop-blur-md shadow-[rgba(15,15,15,0.05)_0px_1px_2px_0px,rgba(15,15,15,0.09)_0px_4px_12px_0px] transition-shadow hover:shadow-[rgba(15,15,15,0.06)_0px_2px_4px_0px,rgba(15,15,15,0.12)_0px_10px_24px_0px] pointer-events-auto"
              >
                <ToolCardBody tool={tool} apiBase={apiBase} />
              </Link>
            )
          }
          return (
            <div
              key={tool.id}
              role="button"
              tabIndex={0}
              aria-disabled="true"
              onClick={() => message.info('没有使用该工具的权限，请联系管理员')}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  message.info('没有使用该工具的权限，请联系管理员')
                }
              }}
              className="block cursor-not-allowed rounded-xl border border-[var(--color-hairline-soft)] bg-[var(--color-surface)] p-5 select-none pointer-events-auto"
            >
              <ToolCardBody tool={tool} apiBase={apiBase} muted />
              <span className="mt-3 inline-flex items-center gap-1 text-[12px] text-[var(--color-stone)]">
                <LockOutlined style={{ fontSize: 11 }} />
                无权限
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
