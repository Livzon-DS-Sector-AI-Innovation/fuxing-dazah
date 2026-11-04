'use client'

import { useRef } from 'react'
import { Button, theme, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { EnvTrend } from '@/types/quality'

/** 点位环境监测趋势图：纯 SVG 实现（与汇总统计趋势同方案，无图表库依赖）。
 *  数据折线 + 警戒限/行动限虚线 + 按判定着色数据点，支持导出 PNG。 */
export default function EnvTrendChart({ trend }: { trend: EnvTrend }) {
  const { token } = theme.useToken()
  const svgRef = useRef<SVGSVGElement>(null)
  const pts = trend.items.filter((p) => p.result_value != null)
  if (pts.length < 2) {
    return <Typography.Text type="secondary">该点位有效记录不足 2 条，无法绘制趋势（至少填报两次后再看）。</Typography.Text>
  }

  const handleExportPng = () => {
    const svg = svgRef.current
    if (!svg) return
    const xml = new XMLSerializer().serializeToString(svg)
    const img = new Image()
    const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = 1520
      canvas.height = 600
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png')
      a.download = `环境趋势-${trend.room}-${trend.point_no}.png`
      a.click()
    }
    img.src = url
  }

  const W = 760
  const H = 300
  const PL = 56
  const PR = 16
  const PT = 24
  const PB = 46

  const values = pts.map((p) => p.result_value as number)
  const limits = [trend.alert_limit, trend.action_limit].filter((v): v is number => v != null)
  const all = [...values, ...limits]
  const rawMin = Math.min(...all)
  const rawMax = Math.max(...all)
  const pad = (rawMax - rawMin) * 0.1 || Math.abs(rawMax) * 0.08 || 1
  const yMin = Math.max(0, rawMin - pad)
  const yMax = rawMax + pad
  const yOf = (v: number) => H - PB - ((v - yMin) / (yMax - yMin)) * (H - PT - PB)
  const xOf = (i: number) => (pts.length === 1 ? PL : PL + (i / (pts.length - 1)) * (W - PL - PR))

  const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1))

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Button size="small" icon={<DownloadOutlined />} onClick={handleExportPng}>导出 PNG</Button>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        {/* 网格与 Y 轴刻度 */}
        {[yMin, yMax].map((v) => (
          <g key={`grid-${v}`}>
            <line x1={PL} y1={yOf(v)} x2={W - PR} y2={yOf(v)} stroke={token.colorBorderSecondary} strokeWidth={1} />
            <text x={PL - 8} y={yOf(v) + 4} textAnchor="end" fontSize={11} fill={token.colorTextSecondary}>{fmt(v)}</text>
          </g>
        ))}
        {/* 警戒限 / 行动限虚线 */}
        {trend.alert_limit != null && (
          <g>
            <line x1={PL} y1={yOf(trend.alert_limit)} x2={W - PR} y2={yOf(trend.alert_limit)}
              stroke={token.colorWarning} strokeWidth={1.5} strokeDasharray="6 4" />
            <text x={PL - 8} y={yOf(trend.alert_limit) + 4} textAnchor="end" fontSize={11} fill={token.colorWarning}>
              警戒 {fmt(trend.alert_limit)}
            </text>
          </g>
        )}
        {trend.action_limit != null && (
          <g>
            <line x1={PL} y1={yOf(trend.action_limit)} x2={W - PR} y2={yOf(trend.action_limit)}
              stroke={token.colorError} strokeWidth={1.5} strokeDasharray="6 4" />
            <text x={PL - 8} y={yOf(trend.action_limit) + 4} textAnchor="end" fontSize={11} fill={token.colorError}>
              行动 {fmt(trend.action_limit)}
            </text>
          </g>
        )}
        {/* 数据折线 */}
        <polyline
          points={pts.map((p, i) => `${xOf(i)},${yOf(p.result_value as number)}`).join(' ')}
          fill="none" stroke={token.colorPrimary} strokeWidth={2}
        />
        {/* 数据点按判定着色 */}
        {pts.map((p, i) => {
          const color = p.judge === 'action' ? token.colorError : p.judge === 'alert' ? token.colorWarning : token.colorSuccess
          return (
            <circle
              key={`${p.record_date}-${i}`}
              cx={xOf(i)} cy={yOf(p.result_value as number)} r={3.5}
              fill={color}
            >
              <title>{`${p.record_date}: ${p.result_value}`}</title>
            </circle>
          )
        })}
        {/* X 轴日期标签（首/中/尾） */}
        {[0, Math.floor((pts.length - 1) / 2), pts.length - 1].map((i) => (
          <text
            key={`x-${i}`}
            x={xOf(i)}
            y={H - PB + 18}
            textAnchor={i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}
            fontSize={11}
            fill={token.colorTextSecondary}
          >
            {pts[i].record_date.slice(5)}
          </text>
        ))}
      </svg>
    </div>
  )
}
