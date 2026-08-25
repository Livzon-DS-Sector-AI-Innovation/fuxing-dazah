'use client'

import { useMemo, useState } from 'react'
import { Empty, Select, Spin, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchFieldTrendClient } from '@/lib/api/production-client'
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

export function FieldTrendChart({ productId }: { productId: string }) {
  const [routeId, setRouteId] = useState<string | undefined>()
  const [nodeCode, setNodeCode] = useState<string | undefined>()
  const [fieldKey, setFieldKey] = useState<string | undefined>()
  // 按填写时间过滤趋势数据点 ['YYYY-MM-DD', 'YYYY-MM-DD']；null=全部
  const { dateRange, picker } = useDateRangeState()

  const graph = useRouteGraph('trend', routeId)

  const node = useMemo(
    () => graph?.nodes.find(n => n.node_code === nodeCode) ?? null,
    [graph, nodeCode],
  )
  const fieldOptions = useMemo(
    () => (node?.fields ?? [])
      .filter(f => f.data_type === 'numeric')
      .map(f => ({ label: f.unit ? `${f.field_label}（${f.unit}）` : f.field_label, value: f.field_key })),
    [node],
  )

  const { data: points = [], isLoading } = useQuery({
    queryKey: ['production-field-trend', routeId, nodeCode, fieldKey],
    queryFn: () => fetchFieldTrendClient(routeId!, nodeCode!, fieldKey!),
    enabled: !!routeId && !!nodeCode && !!fieldKey,
  })

  // 按填写时间过滤趋势点。filled_at 是带 +00:00 偏移的 ISO 串，
  // 用 dayjs 解析后按本地时区取日期，避免 00:00–08:00 时段错位一天
  const filteredPoints = useMemo(() => {
    if (!dateRange) return points
    const [start, end] = dateRange
    return points.filter(p => {
      const d = dayjs(p.filled_at).format('YYYY-MM-DD')
      return d >= start && d <= end
    })
  }, [points, dateRange])

  const many = filteredPoints.length > 15
  const option = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    grid: { left: 52, right: 24, top: 40, bottom: many ? 52 : 32 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: v => (v == null ? '-' : Number(v as number).toFixed(2)),
    },
    xAxis: {
      type: 'category',
      data: filteredPoints.map(p => p.batch_no),
      boundaryGap: false,
      // 数据多时自动跳格显示标签，避免叠加挤压；配合 dataZoom 可拖动/缩放细看
      axisLabel: { color: T.stone, fontSize: 11, interval: 'auto', hideOverlap: true },
      axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: T.stone, fontSize: 11 },
      splitLine: { lineStyle: { color: T.hairline } },
    },
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
    series: [{ name: '数值', type: 'line', symbolSize: 5, data: filteredPoints.map(p => p.value) }],
  }), [filteredPoints, many])

  const ready = !!routeId && !!nodeCode && !!fieldKey
  const hasData = ready && filteredPoints.length > 0

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <RouteSelect
          productId={productId}
          style={{ minWidth: 220 }}
          value={routeId}
          onChange={v => { setRouteId(v); setNodeCode(undefined); setFieldKey(undefined) }}
        />
        <Select
          allowClear
          showSearch={{ optionFilterProp: 'label' }}
          placeholder="选择工序"
          style={{ minWidth: 160 }}
          value={nodeCode}
          onChange={v => { setNodeCode(v); setFieldKey(undefined) }}
          disabled={!routeId}
          options={(graph?.nodes ?? []).map(n => ({ label: n.name, value: n.node_code }))}
        />
        <Select
          allowClear
          placeholder="选择数值字段"
          style={{ minWidth: 180 }}
          value={fieldKey}
          onChange={setFieldKey}
          disabled={!nodeCode || fieldOptions.length === 0}
          options={fieldOptions}
        />
        {picker}
      </div>

      <Spin spinning={isLoading}>
        {hasData ? (
          <ReactECharts option={option} style={{ height: 320 }} notMerge />
        ) : (
          <div style={{ padding: '48px 0' }}>
            <Empty
              description={
                !ready
                  ? '选择路线、工序和数值字段后查看字段趋势'
                  : dateRange && points.length > 0
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
          共 {filteredPoints.length} 个数据点，按填写时间排序
        </Text>
      )}
    </div>
  )
}
