'use client'

import { useMemo } from 'react'
import { Alert, Empty, Spin } from 'antd'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { antdTheme } from '@/lib/antd-theme'
import { AprMeta } from './AprChrome'
import type { AprTrend, AprTrendPointStatus } from '@/types/qa-apr'

// ECharts 画在 canvas 上，读不到 CSS 变量，统一从 antd 主题 token 取色（与 DESIGN.md 同源）。
// 轴标签用 steel(#787671, 对白底约 4.7:1) 承载 11px 文字：quaternary 只有约 2.5:1，达不到 AA。
const TOKEN = antdTheme.token!
const T = {
  stone: TOKEN.colorTextTertiary!,
  hairline: TOKEN.colorBorder!,
}
const LINE_COLOR = TOKEN.colorPrimary!
const SPEC_COLOR = TOKEN.colorError!
const OOT_COLOR = TOKEN.colorWarning!
const MEAN_COLOR = TOKEN.colorSuccess!
// ±3σ 用 brand-teal：link-blue 在 DESIGN.md 里是行内链接专用色，不承担数据条目的语义。
const SIGMA_COLOR = '#2a9d99'
const STATUS_COLOR: Record<AprTrendPointStatus, string> = {
  normal: LINE_COLOR,
  oot: OOT_COLOR,
  oos: SPEC_COLOR,
}
const STATUS_LABEL: Record<AprTrendPointStatus, string> = {
  normal: '正常',
  oot: 'OOT 预警',
  oos: 'OOS 超标',
}

type MarkLine = {
  yAxis: number
  name: string
  color: string
  type: 'solid' | 'dashed' | 'dotted'
  /** 均值/±3σ 的数值已经写在图表上方的元信息里，参考线不再重复标注，避免多条标签挤在一起。 */
  labelled?: boolean
}

/** 单列趋势图：批次折线 + Spec/OOT/均值/±3σ 参考线，OOS/OOT 点分色。 */
export function AprTrendChart({
  trend,
  loading = false,
  error = null,
}: {
  trend: AprTrend | null
  loading?: boolean
  /** 请求失败原因：与「还没选列/暂无数据」的空态区分开，不误导用户。 */
  error?: string | null
}) {
  const option = useMemo<EChartsOption | null>(() => {
    if (!trend || trend.points.length === 0) return null
    const { item, stats, points } = trend
    const markLines: MarkLine[] = []
    if (item.spec_max != null) markLines.push({ yAxis: item.spec_max, name: `标准上限 ${item.spec_max}`, color: SPEC_COLOR, type: 'solid' })
    if (item.spec_min != null) markLines.push({ yAxis: item.spec_min, name: `标准下限 ${item.spec_min}`, color: SPEC_COLOR, type: 'solid' })
    if (item.oot_max != null) markLines.push({ yAxis: item.oot_max, name: `OOT 上限 ${item.oot_max}`, color: OOT_COLOR, type: 'dashed' })
    if (item.oot_min != null) markLines.push({ yAxis: item.oot_min, name: `OOT 下限 ${item.oot_min}`, color: OOT_COLOR, type: 'dashed' })
    if (stats.mean != null) markLines.push({ yAxis: stats.mean, name: `均值 ${stats.mean.toFixed(4)}`, color: MEAN_COLOR, type: 'dotted', labelled: false })
    if (stats.plus3s != null) markLines.push({ yAxis: stats.plus3s, name: `+3σ ${stats.plus3s.toFixed(4)}`, color: SIGMA_COLOR, type: 'dotted', labelled: false })
    if (stats.minus3s != null) markLines.push({ yAxis: stats.minus3s, name: `-3σ ${stats.minus3s.toFixed(4)}`, color: SIGMA_COLOR, type: 'dotted', labelled: false })

    const many = points.length > 15
    return {
      grid: { left: 56, right: 24, top: 40, bottom: many ? 56 : 48 },
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex?: number }
          const idx = first?.dataIndex ?? 0
          const p = points[idx]
          if (!p) return ''
          return [
            `批号：${p.batch_no}${p.row_seq > 1 ? `（第 ${p.row_seq} 行）` : ''}`,
            p.nd
              ? `数值：${p.text ?? '未检出'}（按 0 计入统计）`
              : `数值：${p.value}${item.unit ?? ''}`,
            `状态：${STATUS_LABEL[p.status]}`,
          ].join('<br/>')
        },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => (p.row_seq > 1 ? `${p.batch_no}·${p.row_seq}` : p.batch_no)),
        axisLabel: { color: T.stone, fontSize: 11, rotate: points.length > 8 ? 35 : 0 },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis: {
        type: 'value',
        // 轴顶标单位，和表内数值的单位提醒保持一致
        name: item.unit ?? '',
        nameTextStyle: { color: T.stone, fontSize: 11 },
        // scale: 不从 0 起算。工艺参数（pH、温度、含量）的有效区间往往很窄，
        // 强制从 0 起会把整条趋势压成一条直线，看不出波动。
        scale: true,
        axisLabel: { color: T.stone, fontSize: 11 },
        splitLine: { lineStyle: { color: T.hairline } },
      },
      ...(many
        ? { dataZoom: [{ type: 'slider' as const, height: 18, bottom: 8 }] }
        : {}),
      series: [
        {
          type: 'line',
          name: item.name_cn,
          symbolSize: 8,
          lineStyle: { color: LINE_COLOR, width: 2 },
          itemStyle: { color: LINE_COLOR },
          data: points.map((p) => ({
            value: p.value,
            // 未检出点画空心：位置是口径映射的 0，不是实测值
            itemStyle: p.nd
              ? { color: '#fff', borderColor: STATUS_COLOR[p.status], borderWidth: 2 }
              : { color: STATUS_COLOR[p.status] },
          })),
          markLine: {
            symbol: 'none',
            label: { position: 'insideEndTop', fontSize: 10, color: T.stone },
            data: markLines.map((m) => ({
              name: m.name,
              yAxis: m.yAxis,
              lineStyle: { color: m.color, type: m.type, width: 1 },
              label: { show: m.labelled !== false, formatter: m.name, color: m.color },
            })),
          },
        },
      ],
    }
  }, [trend])

  if (loading) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon title="趋势加载失败" description={error} />
      </div>
    )
  }
  if (!trend) return <Empty description="选择一个数值列查看趋势" style={{ padding: 24 }} />
  if (!option) return <Empty description="该列暂无数据点" style={{ padding: 24 }} />

  const { stats } = trend
  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 12,
          flexWrap: 'wrap',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 6,
        }}
      >
        <AprMeta
          items={[
            `n = ${stats.count}`,
            stats.nd_count != null && stats.nd_count > 0
              ? `未检出 ${stats.nd_count}`
              : false,
            stats.mean != null ? `均值 ${stats.mean.toFixed(4)}` : false,
            stats.stdev != null ? `σ ${stats.stdev.toFixed(4)}` : false,
            stats.min != null ? `范围 ${stats.min} ~ ${stats.max}` : false,
          ]}
        />
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          {(['normal', 'oot', 'oos'] as AprTrendPointStatus[]).map((status) => (
            <span
              key={status}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                fontSize: 11,
                lineHeight: '16px',
                color: 'var(--color-steel)',
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: STATUS_COLOR[status],
                }}
              />
              {STATUS_LABEL[status]}
            </span>
          ))}
        </div>
      </div>
      <ReactECharts option={option} style={{ height: 340 }} notMerge />
    </div>
  )
}
