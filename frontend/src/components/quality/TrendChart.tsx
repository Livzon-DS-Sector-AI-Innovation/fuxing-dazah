'use client'

import { useRef } from 'react'
import { useRouter } from 'next/navigation'
import type { SummaryTrend } from '@/types/quality'

const GOOD = '#0ca30c'
const CRITICAL = '#d03b3b'

/** 项目跨批次趋势图：纯 SVG 实现（无图表库依赖，渲染稳定）。
 *  单序列折线 + 上下限度虚线 + 均值 ±3σ 控制线 + 合格/不合格点着色。
 *  数据点可点击跳转对应任务详情。 */
export default function TrendChart({ trend }: { trend: SummaryTrend }) {
  const router = useRouter()
  const svgRef = useRef<SVGSVGElement>(null)
  const pts = trend.points.filter((p) => p.value != null)
  if (pts.length < 2) return null

  // 导出 PNG：SVG 序列化 → canvas 2x 渲染 → 下载
  const handleExportPng = () => {
    const svg = svgRef.current
    if (!svg) return
    const xml = new XMLSerializer().serializeToString(svg)
    const img = new Image()
    const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = 1600
      canvas.height = 600
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png')
      a.download = `趋势-${trend.item_name}.png`
      a.click()
    }
    img.src = url
  }

  const W = 800
  const H = 300
  const PL = 56
  const PR = 20
  const PT = 26
  const PB = 46

  const values = pts.map((p) => p.value as number)
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const std = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (values.length - 1))
  const limits = [trend.limit_min, trend.limit_max].filter((v): v is number => v != null)
  const all = [...values, ...limits, mean - 3 * std, mean + 3 * std]
  const rawMin = Math.min(...all)
  const rawMax = Math.max(...all)
  const pad = (rawMax - rawMin) * 0.12 || Math.abs(rawMax) * 0.1 || 1
  const y0 = rawMin - pad
  const y1 = rawMax + pad

  const x = (i: number) => PL + (i * (W - PL - PR)) / (pts.length - 1)
  const y = (v: number) => PT + (1 - (v - y0) / (y1 - y0)) * (H - PT - PB)
  const labelEvery = Math.max(1, Math.ceil(pts.length / 7))
  const ooc = (v: number) => Math.abs(v - mean) > 3 * std  // 超控制限标记

  return (
    <div>
      <div style={{ textAlign: 'right', marginBottom: 4 }}>
        <button
          onClick={handleExportPng}
          style={{
            border: '1px solid #d9d9d9', background: '#fff', borderRadius: 4,
            padding: '2px 10px', fontSize: 12, cursor: 'pointer',
          }}
        >
          导出图片
        </button>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', minHeight: 200 }}>
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
        {/* 控制线：均值 ±3σ */}
        <line x1={PL} x2={W - PR} y1={y(mean)} y2={y(mean)} stroke="#9c9c9c" strokeWidth={1} />
        <line x1={PL} x2={W - PR} y1={y(mean + 3 * std)} y2={y(mean + 3 * std)} stroke="#9c9c9c" strokeDasharray="3 4" strokeWidth={1} />
        <line x1={PL} x2={W - PR} y1={y(mean - 3 * std)} y2={y(mean - 3 * std)} stroke="#9c9c9c" strokeDasharray="3 4" strokeWidth={1} />
        <text x={W - PR} y={y(mean) - 3} fontSize={9} fill="#9c9c9c" textAnchor="end">均值 {mean.toFixed(2)}</text>
        <text x={W - PR} y={y(mean + 3 * std) - 3} fontSize={9} fill="#9c9c9c" textAnchor="end">+3σ {(+3 * std + mean).toFixed(2)}</text>
        <text x={W - PR} y={y(mean - 3 * std) + 11} fontSize={9} fill="#9c9c9c" textAnchor="end">-3σ {(mean - 3 * std).toFixed(2)}</text>
        {/* 限度线 */}
        {trend.limit_max != null && (
          <g>
            <line x1={PL} x2={W - PR} y1={y(trend.limit_max)} y2={y(trend.limit_max)} stroke={CRITICAL} strokeDasharray="5 4" strokeWidth={1} />
            <text x={W - PR} y={y(trend.limit_max) - 4} fontSize={10} fill={CRITICAL} textAnchor="end">
              上限 {trend.limit_max}{trend.unit}
            </text>
          </g>
        )}
        {trend.limit_min != null && (
          <g>
            <line x1={PL} x2={W - PR} y1={y(trend.limit_min)} y2={y(trend.limit_min)} stroke={GOOD} strokeDasharray="5 4" strokeWidth={1} />
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
          <g
            key={i}
            style={{ cursor: 'pointer' }}
            onClick={() => router.push(`/quality/task/${p.task_id}`)}
          >
            <circle
              cx={x(i)}
              cy={y(p.value as number)}
              r={4.5}
              fill={p.is_pass ? GOOD : CRITICAL}
              stroke="#fff"
              strokeWidth={1.5}
            >
              <title>
                {`${p.batch_number}：${p.value}${trend.unit}（${p.is_pass ? '合格' : '不合格'}${ooc(p.value as number) ? '，超出控制限' : ''}）点击查看任务`}
              </title>
            </circle>
            {ooc(p.value as number) && (
              <circle cx={x(i)} cy={y(p.value as number)} r={8} fill="none" stroke={CRITICAL} strokeWidth={1.5} strokeDasharray="2 2" />
            )}
          </g>
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
        <span style={{ marginRight: 14 }}>虚线圆圈 = 超出均值 ±3σ 控制限</span>
        <span>点击数据点打开任务详情；悬停查看数值</span>
      </div>
    </div>
  )
}
