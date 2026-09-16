'use client'

import type { SummaryTrend } from '@/types/quality'

const GOOD = '#0ca30c'
const CRITICAL = '#d03b3b'

/** 项目跨批次趋势图：纯 SVG 实现（无图表库依赖，渲染稳定）。
 *  单序列折线 + 上下限度虚线 + 合格/不合格点着色 + 原生悬停提示。 */
export default function TrendChart({ trend }: { trend: SummaryTrend }) {
  const pts = trend.points.filter((p) => p.value != null)
  if (pts.length < 2) return null

  const W = 800
  const H = 280
  const PL = 56
  const PR = 20
  const PT = 26
  const PB = 46

  const values = pts.map((p) => p.value as number)
  const limits = [trend.limit_min, trend.limit_max].filter((v): v is number => v != null)
  const all = [...values, ...limits]
  const rawMin = Math.min(...all)
  const rawMax = Math.max(...all)
  const pad = (rawMax - rawMin) * 0.12 || Math.abs(rawMax) * 0.1 || 1
  const y0 = rawMin - pad
  const y1 = rawMax + pad

  const x = (i: number) => PL + (i * (W - PL - PR)) / (pts.length - 1)
  const y = (v: number) => PT + (1 - (v - y0) / (y1 - y0)) * (H - PT - PB)
  const labelEvery = Math.max(1, Math.ceil(pts.length / 7))

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', minHeight: 200 }}>
        {[0.25, 0.5, 0.75].map((r) => (
          <line
            key={r}
            x1={PL}
            x2={W - PR}
            y1={PT + r * (H - PT - PB)}
            y2={PT + r * (H - PT - PB)}
            stroke="#f0f0f0"
            strokeDasharray="3 3"
          />
        ))}
        {trend.limit_max != null && (
          <g>
            <line
              x1={PL}
              x2={W - PR}
              y1={y(trend.limit_max)}
              y2={y(trend.limit_max)}
              stroke={CRITICAL}
              strokeDasharray="5 4"
              strokeWidth={1}
            />
            <text x={W - PR} y={y(trend.limit_max) - 4} fontSize={10} fill={CRITICAL} textAnchor="end">
              上限 {trend.limit_max}{trend.unit}
            </text>
          </g>
        )}
        {trend.limit_min != null && (
          <g>
            <line
              x1={PL}
              x2={W - PR}
              y1={y(trend.limit_min)}
              y2={y(trend.limit_min)}
              stroke={GOOD}
              strokeDasharray="5 4"
              strokeWidth={1}
            />
            <text x={W - PR} y={y(trend.limit_min) + 12} fontSize={10} fill={GOOD} textAnchor="end">
              下限 {trend.limit_min}{trend.unit}
            </text>
          </g>
        )}
        <polyline
          points={pts.map((p, i) => `${x(i)},${y(p.value as number)}`).join(' ')}
          fill="none"
          stroke="#6b6b6b"
          strokeWidth={2}
        />
        {pts.map((p, i) => (
          <circle
            key={i}
            cx={x(i)}
            cy={y(p.value as number)}
            r={4.5}
            fill={p.is_pass ? GOOD : CRITICAL}
            stroke="#fff"
            strokeWidth={1.5}
          >
            <title>
              {`${p.batch_number}：${p.value}${trend.unit}（${p.is_pass ? '合格' : '不合格'}）`}
            </title>
          </circle>
        ))}
        {pts.map((p, i) =>
          (i % labelEvery === 0 || i === pts.length - 1) && (
            <text key={`x${i}`} x={x(i)} y={H - 20} fontSize={10} fill="#a4a097" textAnchor="middle">
              {p.batch_number}
            </text>
          ),
        )}
        <text x={PL - 8} y={PT + 4} fontSize={10} fill="#a4a097" textAnchor="end">
          {y1.toFixed(2)}
        </text>
        <text x={PL - 8} y={H - PB + 14} fontSize={10} fill="#a4a097" textAnchor="end">
          {y0.toFixed(2)}
        </text>
      </svg>
      <div style={{ marginTop: 4, fontSize: 12, color: '#8a8a8a' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', marginRight: 14 }}>
          <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: GOOD, marginRight: 5 }} />
          合格
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', marginRight: 14 }}>
          <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: CRITICAL, marginRight: 5 }} />
          不合格
        </span>
        <span>悬停数据点查看批次与数值</span>
      </div>
    </div>
  )
}
