'use client'

import { useMemo } from 'react'
import { Alert, Empty, Spin } from 'antd'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { antdTheme } from '@/lib/antd-theme'
import { AprChromeStyles, AprMeta } from './AprChrome'
import type { AprTrend, AprTrendPointStatus } from '@/types/qa'

// ECharts 画在 canvas 上，读不到 CSS 变量，统一从 antd 主题 token 取色（与 DESIGN.md 同源）。
// 轴标签用 steel(#787671, 对白底约 4.7:1) 承载 12px 文字：quaternary 只有约 2.5:1，达不到 AA。
const TOKEN = antdTheme.token!
const T = {
  stone: TOKEN.colorTextTertiary!,
  hairline: TOKEN.colorBorder!,
}
const LINE_COLOR = TOKEN.colorPrimary!
const SPEC_COLOR = TOKEN.colorError!
const OOT_COLOR = TOKEN.colorWarning!
const MEAN_COLOR = TOKEN.colorSuccess!

/** 主题色十六进制 → 带透明度 rgba（canvas 读不了 CSS 变量，也不能写死色值
 *  跟丢主题换肤）。 */
function withAlpha(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}
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
  /** 均值的数值已经写在图表上方的元信息里，参考线不再重复标注，避免多条标签挤在一起。 */
  labelled?: boolean
}

type ChartRefs = {
  spec: boolean
  oot: boolean
  mean: boolean
}

type LegendItem = {
  key: string
  label: string
  kind: 'line' | 'dot' | 'rule'
  color: string
  border?: 'solid' | 'dashed' | 'dotted'
}

/** 单列趋势图：批次折线 + 标准/OOT/均值参考线（与导出报告同口径，恒画），OOS/OOT 点分色。 */
export function AprTrendChart({
  trend,
  loading = false,
  error = null,
  height = 340,
}: {
  trend: AprTrend | null
  loading?: boolean
  /** 请求失败原因：与「还没选列/暂无数据」的空态区分开，不误导用户。 */
  error?: string | null
  /** 弹窗里给图表更高的画布；页内使用时保持默认。 */
  height?: number
}) {
  const chart = useMemo(() => {
    if (!trend || trend.points.length === 0) return null
    const { item, stats, points } = trend
    const values = points.map((p) => p.value)
    const dataMin = Math.min(...values)
    const dataMax = Math.max(...values)

    // 标准/OOT/均值参考线与导出报告同口径：配置了就恒画（不做贴近过滤），
    // y 轴范围随之扩展到限度线——两边看到的图一致。
    const specLines: MarkLine[] = []
    const ootLines: MarkLine[] = []
    if (item.spec_max != null) {
      specLines.push({
        yAxis: item.spec_max,
        name: `标准上限 ${item.spec_max}`,
        color: SPEC_COLOR,
        type: 'solid',
      })
    }
    if (item.spec_min != null) {
      specLines.push({
        yAxis: item.spec_min,
        name: `标准下限 ${item.spec_min}`,
        color: SPEC_COLOR,
        type: 'solid',
      })
    }
    if (item.oot_max != null) {
      ootLines.push({
        yAxis: item.oot_max,
        name: `OOT 上限 ${item.oot_max}`,
        color: OOT_COLOR,
        type: 'dashed',
      })
    }
    if (item.oot_min != null) {
      ootLines.push({
        yAxis: item.oot_min,
        name: `OOT 下限 ${item.oot_min}`,
        color: OOT_COLOR,
        type: 'dashed',
      })
    }
    const meanLine: MarkLine | null =
      stats.mean != null
        ? {
            yAxis: stats.mean,
            name: `均值 ${stats.mean.toFixed(4)}`,
            color: MEAN_COLOR,
            type: 'dotted',
            labelled: false,
          }
        : null
    const markLines = [
      ...specLines,
      ...ootLines,
      ...(meanLine ? [meanLine] : []),
    ]
    const refs: ChartRefs = {
      spec: specLines.length > 0,
      oot: ootLines.length > 0,
      mean: meanLine != null,
    }

    // 让所有真正画出来的参考线都落在坐标轴内，图例才不会承诺一条看不见的线。
    const axisMin = Math.min(dataMin, ...markLines.map((line) => line.yAxis))
    const axisMax = Math.max(dataMax, ...markLines.map((line) => line.yAxis))
    const axisPad = Math.max(
      (axisMax - axisMin) * 0.06,
      Math.abs(axisMax) * 0.002,
      0.001,
    )
    // 坐标轴取 1/2/5 × 10^n 的整齐步长，避免出现 27.081040695832808 这种刻度。
    const rawMin = axisMin - axisPad
    const rawMax = axisMax + axisPad
    const rough = (rawMax - rawMin) / 5 || 0.001
    const magnitude = 10 ** Math.floor(Math.log10(rough))
    const norm = rough / magnitude
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * magnitude
    const axisStep = Number(step.toPrecision(12))
    const axisFloor = Math.floor(rawMin / axisStep) * axisStep
    const axisCeil = Math.ceil(rawMax / axisStep) * axisStep

    const many = points.length > 15
    const sparse = points.length > 8
    const showYear = new Set(points.map((p) => p.year)).size > 1
    // 38 个长批号全标必然叠在一起；按弹窗宽度定标签数量，每隔几个标一次，悬停仍能看全量。
    const viewport = typeof window === 'undefined' ? 1440 : window.innerWidth
    const chartWidth = Math.min(1180, viewport - 32) - 96
    const targetLabels = Math.max(3, Math.min(8, Math.floor(chartWidth / 110)))
    const labelInterval = Math.max(0, Math.ceil(points.length / targetLabels) - 1)
    const rotate = sparse ? 30 : 0

    const option: EChartsOption = {
      grid: {
        left: 64,
        right: 24,
        top: 40,
        bottom: many ? 104 : sparse ? 78 : 48,
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex?: number }
          const idx = first?.dataIndex ?? 0
          const p = points[idx]
          if (!p) return ''
          return [
            `批号：${p.batch_no}${showYear ? `（${p.year} 年）` : ''}${p.row_seq > 1 ? `（第 ${p.row_seq} 行）` : ''}`,
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
        axisLabel: {
          color: T.stone,
          fontSize: 12,
          interval: labelInterval,
          rotate,
          margin: 8,
          // 窄屏下即便按间隔抽稀也可能碰到，交给 ECharts 再隐藏重叠的标签。
          hideOverlap: true,
        },
        axisTick: { alignWithLabel: true },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis: {
        type: 'value',
        // 轴顶标单位，和表内数值的单位提醒保持一致
        name: item.unit ?? '',
        nameTextStyle: { color: T.stone, fontSize: 12 },
        nameGap: 12,
        min: axisFloor,
        max: axisCeil,
        interval: axisStep,
        axisLabel: {
          color: T.stone,
          fontSize: 12,
          formatter: (value: number) => Number(value.toFixed(4)).toString(),
        },
        splitLine: { lineStyle: { color: T.hairline } },
      },
      ...(many
        ? {
            dataZoom: [
              {
                type: 'slider' as const,
                height: 16,
                bottom: 12,
                brushSelect: false,
                showDetail: false,
                borderColor: T.hairline,
                backgroundColor: 'transparent',
                fillerColor: withAlpha(LINE_COLOR, 0.1),
                handleStyle: { color: '#ffffff', borderColor: T.hairline },
                moveHandleStyle: { color: T.hairline },
                dataBackground: {
                  lineStyle: { color: T.hairline },
                  areaStyle: { color: 'rgba(0, 0, 0, 0.02)' },
                },
                selectedDataBackground: {
                  lineStyle: { color: LINE_COLOR },
                  areaStyle: { color: withAlpha(LINE_COLOR, 0.08) },
                },
              },
            ],
          }
        : {}),
      series: [
        {
          type: 'line',
          name: item.name_cn,
          // 显式实心圆：line 系列默认的 emptyCircle 在部分顶点会露出空心，像未检出点。
          symbol: 'circle',
          symbolSize: 9,
          showSymbol: true,
          lineStyle: { color: LINE_COLOR, width: 2.5 },
          itemStyle: { color: LINE_COLOR, borderColor: '#ffffff', borderWidth: 1 },
          emphasis: { scale: 1.6 },
          data: points.map((p) => ({
            value: p.value,
            // 未检出点画空心：位置是口径映射的 0，不是实测值
            itemStyle: p.nd
              ? { color: '#ffffff', borderColor: STATUS_COLOR[p.status], borderWidth: 2 }
              : {
                  color: STATUS_COLOR[p.status],
                  borderColor: '#ffffff',
                  borderWidth: 1,
                },
          })),
          markLine: {
            symbol: 'none',
            label: { position: 'insideEndTop', fontSize: 11, color: T.stone },
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
    return { option, refs }
  }, [trend])

  if (loading)
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon title="趋势加载失败" description={error} />
      </div>
    )
  }
  if (!trend) return <Empty description="选择一个数值列查看趋势" style={{ padding: 24 }} />
  if (!chart) return <Empty description="该列暂无数据点" style={{ padding: 24 }} />

  const { stats } = trend
  const legendItems: LegendItem[] = [
    { key: 'normal', label: '正常', kind: 'line', color: LINE_COLOR },
    { key: 'oot', label: 'OOT 预警', kind: 'dot', color: OOT_COLOR },
    { key: 'oos', label: 'OOS 超标', kind: 'dot', color: SPEC_COLOR },
  ]
  if (chart.refs.spec) {
    legendItems.push({ key: 'spec', label: '标准限度', kind: 'rule', color: SPEC_COLOR, border: 'solid' })
  }
  if (chart.refs.oot) {
    legendItems.push({ key: 'ootLine', label: 'OOT 限', kind: 'rule', color: OOT_COLOR, border: 'dashed' })
  }
  if (chart.refs.mean) {
    legendItems.push({ key: 'mean', label: '均值', kind: 'rule', color: MEAN_COLOR, border: 'dotted' })
  }

  return (
    <div>
      <div className={AprChromeStyles.trendMeta}>
        <AprMeta
          items={[
            `n = ${stats.count}`,
            stats.nd_count != null && stats.nd_count > 0
              ? `未检出 ${stats.nd_count}`
              : false,
            stats.mean != null ? `均值 ${stats.mean.toFixed(4)}` : false,
            stats.stdev != null ? `σ ${stats.stdev.toFixed(4)}` : false,
            stats.min != null ? `范围 ${stats.min} ~ ${stats.max}` : false,
            stats.cpk != null
              ? `CPK ${stats.cpk.toFixed(2)}${stats.cpk_level ? `（${stats.cpk_level}）` : ''}`
              : false,
          ]}
        />
      </div>
      <div className={AprChromeStyles.chartLegend} role="list" aria-label="图例">
        {legendItems.map((entry) => (
          <span key={entry.key} className={AprChromeStyles.legendItem} role="listitem">
            {entry.kind === 'dot' ? (
              <span
                className={AprChromeStyles.legendDot}
                style={{ background: entry.color }}
              />
            ) : entry.kind === 'line' ? (
              <span
                className={AprChromeStyles.legendLine}
                style={{ background: entry.color }}
              />
            ) : (
              <span
                className={AprChromeStyles.legendRule}
                style={{
                  borderTopColor: entry.color,
                  borderTopStyle: entry.border ?? 'solid',
                }}
              />
            )}
            {entry.label}
          </span>
        ))}
      </div>
      <ReactECharts option={chart.option} style={{ height }} notMerge />
    </div>
  )
}
