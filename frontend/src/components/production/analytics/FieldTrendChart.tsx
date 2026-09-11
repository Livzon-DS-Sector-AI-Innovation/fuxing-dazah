'use client'

import { useMemo, useState } from 'react'
import { Empty, Select, Spin, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchFieldTrendClient } from '@/lib/api/production-client'
import type { FieldTrendSeries } from '@/types/production'
import { antdTheme } from '@/lib/antd-theme'
import { RouteSelect, useRouteGraph } from './RouteSelect'
import { useDateRangeState } from './useDateRange'

const { Text } = Typography

// 图表沿用 antd 主题 token（DESIGN.md 色彩）
const { colorTextQuaternary, colorBorder } = antdTheme.token!
const T = {
  stone: colorTextQuaternary,
  hairline: colorBorder,
}
// 系列色与设备趋势图保持一致
const PALETTE = ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#7b3ff2', '#2a9d99', '#f5d75e', '#ff64c8']

function seriesName(s: FieldTrendSeries): string {
  return s.unit ? `${s.field_label}（${s.unit}）` : s.field_label
}

/**
 * 图例用唯一系列名（field_key → 名）：同标签+单位的字段并列时追加 field_key 区分，
 * 否则 ECharts 按名联动会同时开关两个系列、双轴索引也会错位。
 */
function uniqueSeriesNames(series: FieldTrendSeries[]): Map<string, string> {
  const counts = new Map<string, number>()
  for (const s of series) {
    const base = seriesName(s)
    counts.set(base, (counts.get(base) ?? 0) + 1)
  }
  return new Map(
    series.map(s => {
      const base = seriesName(s)
      return [s.field_key, (counts.get(base) ?? 0) > 1 ? `${base}·${s.field_key}` : base]
    }),
  )
}

export function FieldTrendChart({ productId }: { productId: string }) {
  const [routeId, setRouteId] = useState<string | undefined>()
  const [nodeCode, setNodeCode] = useState<string | undefined>()
  // legend 选中态（系列名 → 是否显示），空对象 = 全部显示；切换路线/工序时重置
  const [legendSelected, setLegendSelected] = useState<Record<string, boolean>>({})
  // 按填写时间过滤趋势数据点 ['YYYY-MM-DD', 'YYYY-MM-DD']；null=全部
  const { dateRange, picker } = useDateRangeState()

  const graph = useRouteGraph('trend', routeId)

  const { data, isLoading } = useQuery({
    queryKey: ['production-field-trend', routeId, nodeCode],
    queryFn: () => fetchFieldTrendClient(routeId!, nodeCode!),
    enabled: !!routeId && !!nodeCode,
  })
  const allSeries = useMemo(() => data?.series ?? [], [data])
  const namesByKey = useMemo(() => uniqueSeriesNames(allSeries), [allSeries])

  // 按填写时间过滤各字段数据点，时间段内无数据的字段整条隐藏（图例不出现）。
  // filled_at 是带 +00:00 偏移的 ISO 串，用 dayjs 解析后按本地时区取日期，
  // 避免 00:00–08:00 时段错位一天
  const filteredSeries = useMemo(() => {
    if (!dateRange) return allSeries
    const [start, end] = dateRange
    return allSeries
      .map(s => ({
        ...s,
        data_points: s.data_points.filter(p => {
          const d = dayjs(p.filled_at).format('YYYY-MM-DD')
          return d >= start && d <= end
        }),
      }))
      .filter(s => s.data_points.length > 0)
  }, [allSeries, dateRange])

  // legend 取消的字段不参与 x 轴批次与坐标轴计算
  const visibleSeries = useMemo(
    () => filteredSeries.filter(s => legendSelected[namesByKey.get(s.field_key)!] !== false),
    [filteredSeries, legendSelected, namesByKey],
  )

  // x 轴批次：可见字段的批次并集，按各批最早填写时间排序（跨字段统一时间序）
  const batchNos = useMemo(() => {
    const firstAt = new Map<string, string>()
    for (const s of visibleSeries) {
      for (const p of s.data_points) {
        const prev = firstAt.get(p.batch_no)
        if (prev === undefined || p.filled_at < prev) firstAt.set(p.batch_no, p.filled_at)
      }
    }
    return [...firstAt.entries()]
      .sort(([, a], [, b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([no]) => no)
  }, [visibleSeries])

  // 恰好剩 2 个可见字段时用左右双 y 轴：量纲差异大的两个字段也能对比变化形态
  const dual = visibleSeries.length === 2
  const many = batchNos.length > 15
  const option = useMemo<EChartsOption>(() => {
    const valueAxis = {
      type: 'value' as const,
      axisLabel: { color: T.stone, fontSize: 11 },
      splitLine: { lineStyle: { color: T.hairline } },
    }
    // 双轴时右轴隐藏网格线，避免两组 splitLine 交叉干扰
    const yAxis = dual
      ? [valueAxis, { ...valueAxis, splitLine: { show: false } }]
      : [valueAxis]
    const option: EChartsOption = {
      color: PALETTE,
      grid: { left: 52, right: dual ? 56 : 24, top: 48, bottom: many ? 52 : 32 },
      legend: {
        top: 8,
        textStyle: { color: T.stone, fontSize: 12 },
        selected: legendSelected,
        // 字段多时图例改单行滚动，避免换行挤压图表
        ...(filteredSeries.length > 8 ? { type: 'scroll' as const } : {}),
      },
      tooltip: {
        trigger: 'axis',
        valueFormatter: v => (v == null ? '-' : Number(v as number).toFixed(2)),
      },
      xAxis: {
        type: 'category',
        data: batchNos,
        boundaryGap: false,
        // 数据多时自动跳格显示标签，避免叠加挤压；配合 dataZoom 可拖动/缩放细看
        axisLabel: { color: T.stone, fontSize: 11, interval: 'auto', hideOverlap: true },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis,
      // 点过多时提供滚轮/拖拽缩放 + 底部缩放条，标签不会被挤在一起
      dataZoom: many
        ? [
            { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, throttle: 50 },
            {
              type: 'slider',
              xAxisIndex: 0,
              bottom: 4,
              height: 16,
              borderColor: 'transparent',
              backgroundColor: '#f6f5f4',
              fillerColor: 'rgba(86,69,212,0.12)',
              handleStyle: { color: '#b9b2f0', borderColor: '#5645d4' },
            },
          ]
        : undefined,
      series: filteredSeries.map(s => {
        const name = namesByKey.get(s.field_key) ?? s.field_label
        const byBatch = new Map(s.data_points.map(p => [p.batch_no, p.value]))
        return {
          name,
          type: 'line',
          symbolSize: 5,
          // 某批未填该字段 → 该点为 null、线跨缺口连接，只对比有填写的数据
          connectNulls: true,
          yAxisIndex: dual && visibleSeries.indexOf(s) === 1 ? 1 : 0,
          data: batchNos.map(b => byBatch.get(b) ?? null),
        }
      }),
    }
    return option
  }, [filteredSeries, visibleSeries, batchNos, dual, many, legendSelected, namesByKey])

  // ECharts legend 点击后同步选中态进 state，并写回 option.legend.selected 防止 setOption 重置
  const onEvents = useMemo(
    () => ({
      legendselectchanged: (params: { selected?: Record<string, boolean> }) => {
        if (params.selected) setLegendSelected(params.selected)
      },
    }),
    [],
  )

  const ready = !!routeId && !!nodeCode
  const hasData = ready && filteredSeries.length > 0

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <RouteSelect
          productId={productId}
          style={{ minWidth: 220 }}
          value={routeId}
          onChange={v => { setRouteId(v); setNodeCode(undefined); setLegendSelected({}) }}
        />
        <Select
          allowClear
          showSearch={{ optionFilterProp: 'label' }}
          placeholder="选择工序"
          style={{ minWidth: 160 }}
          value={nodeCode}
          onChange={v => { setNodeCode(v); setLegendSelected({}) }}
          disabled={!routeId}
          options={(graph?.nodes ?? []).map(n => ({ label: n.name, value: n.node_code }))}
        />
        {picker}
      </div>

      <Spin spinning={isLoading}>
        {hasData ? (
          <ReactECharts option={option} style={{ height: 320 }} notMerge onEvents={onEvents} />
        ) : (
          <div style={{ padding: '48px 0' }}>
            <Empty
              description={
                !ready
                  ? '选择路线和工序后查看字段趋势'
                  : dateRange && allSeries.length > 0
                    ? '该时间段内暂无已填报数据'
                    : '该工序暂无已填报的数值数据'
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        )}
      </Spin>

      {ready && hasData && (
        <Text type="secondary" style={{ fontSize: 12, color: T.stone }}>
          共 {batchNos.length} 个批次、{visibleSeries.length} 个数值字段，按填写时间排序；点击图例可显示/隐藏字段
          {(data?.merged_routes?.length ?? 0) > 0 && `；已合并历史版本：${data!.merged_routes.join('、')}`}
        </Text>
      )}
    </div>
  )
}
