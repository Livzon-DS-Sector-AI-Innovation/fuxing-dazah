'use client'

/** 判定漏斗：左半 ragplus 留痕（发现→解析）+ 右半本仓留痕（推送→去重→判定→收录）。 */

import { EmptyGuide } from '@/components/ui-kit'
import type { RegulationAiFunnel } from '@/types/safety'

export default function AiFunnel({ funnel }: { funnel: RegulationAiFunnel }) {
  const ragplusStages: Array<{ label: string; value: number | null }> = [
    { label: '发现', value: funnel.discovered },
    { label: '解析成功', value: funnel.parsed },
  ]
  const dazahStages: Array<{ label: string; value: number }> = [
    { label: '推送候选', value: funnel.received },
    { label: '去重命中', value: funnel.deduped },
    { label: 'AI 判定', value: funnel.ai_judged },
    { label: '收录入库', value: funnel.promoted },
  ]

  const hasData =
    (funnel.discovered ?? 0) > 0 || funnel.received > 0 || funnel.promoted > 0
  if (!hasData) {
    return (
      <EmptyGuide
        compact
        title="暂无漏斗数据"
        description={`近 ${funnel.window_days} 天无收录运行留痕`}
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        <PipelineLabel text="ragplus 采集留痕" tone="#2f6bd8" />
        {ragplusStages.map((s, i) => (
          <Stage key={s.label} {...s} muted={s.value == null} first={i === 0} />
        ))}
        <span style={{ color: 'var(--color-steel, #8a8a8a)', fontSize: 18 }}>→</span>
        <PipelineLabel text="本仓收录留痕" tone="#5645d4" />
        {dazahStages.map((s) => (
          <Stage key={s.label} label={s.label} value={s.value} />
        ))}
      </div>
      <div style={{ fontSize: 12, color: 'var(--color-steel, #8a8a8a)' }}>
        近 {funnel.window_days} 天口径 · 判定不相关 {funnel.rejected} 条在 AI 判定层流出；
        左半为空说明 ragplus 未透出采集计数（防御降级显示 —）。
      </div>
    </div>
  )
}

function PipelineLabel({ text, tone }: { text: string; tone: string }) {
  return (
    <span
      style={{
        fontSize: 11,
        color: tone,
        border: `1px solid ${tone}33`,
        borderRadius: 999,
        padding: '1px 8px',
        marginRight: 4,
        flexShrink: 0,
      }}
    >
      {text}
    </span>
  )
}

function Stage({
  label,
  value,
  muted = false,
  first = false,
}: {
  label: string
  value: number | null
  muted?: boolean
  first?: boolean
}) {
  return (
    <>
      {!first && (
        <span style={{ color: 'var(--color-steel, #8a8a8a)', fontSize: 14 }}>›</span>
      )}
      <div
        style={{
          textAlign: 'center',
          minWidth: 64,
          padding: '6px 10px',
          borderRadius: 8,
          background: muted ? 'transparent' : 'var(--color-primary-50, #f5f3ff)',
          border: '1px solid var(--color-hairline, #eee)',
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {value ?? '—'}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-steel, #8a8a8a)' }}>{label}</div>
      </div>
    </>
  )
}
