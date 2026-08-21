'use client'

import { useMemo, useState } from 'react'
import { Empty, Select, Spin, Typography } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { fetchFieldTrendClient } from '@/lib/api/production-client'
import { antdTheme } from '@/lib/antd-theme'
import { RouteSelect, useRouteGraph } from './RouteSelect'

const { Text } = Typography

// 图表沿用 antd 主题 token（DESIGN.md 色彩）
const { colorPrimary, colorBgContainer, colorText, colorTextSecondary, colorTextQuaternary, colorBorder } = antdTheme.token!
const T = {
  primary: colorPrimary,
  canvas: colorBgContainer,
  ink: colorText,
  slate: colorTextSecondary,
  stone: colorTextQuaternary,
  hairline: colorBorder,
}
// 系列色与设备趋势图保持一致
const PALETTE = ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#7b3ff2', '#2a9d99', '#f5d75e', '#ff64c8']

export function FieldTrendChart() {
  const [routeId, setRouteId] = useState<string | undefined>()
  const [nodeCode, setNodeCode] = useState<string | undefined>()
  const [fieldKey, setFieldKey] = useState<string | undefined>()

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

  const option = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    grid: { left: 52, right: 24, top: 40, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: v => (v == null ? '-' : Number(v as number).toFixed(2)),
    },
    xAxis: {
      type: 'category',
      data: points.map(p => p.filled_at.slice(0, 16).replace('T', ' ')),
      boundaryGap: false,
      axisLabel: { color: T.stone, fontSize: 11, hideOverlap: true },
      axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: T.stone, fontSize: 11 },
      splitLine: { lineStyle: { color: T.hairline } },
    },
    series: [{ name: '数值', type: 'line', symbolSize: 5, data: points.map(p => p.value) }],
  }), [points])

  const ready = !!routeId && !!nodeCode && !!fieldKey
  const hasData = ready && points.length > 0

  return (
    <div style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <LineChartOutlined style={{ color: T.primary, fontSize: 18 }} />
        <span style={{ fontSize: 22, fontWeight: 600, color: T.ink }}>字段趋势</span>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <RouteSelect
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
      </div>

      <Spin spinning={isLoading}>
        {hasData ? (
          <ReactECharts option={option} style={{ height: 320 }} notMerge />
        ) : (
          <div style={{ padding: '48px 0' }}>
            <Empty
              description={
                ready
                  ? '该工序暂无已填报的数值数据'
                  : '选择路线、工序和数值字段后查看字段趋势'
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        )}
      </Spin>

      {ready && hasData && (
        <Text type="secondary" style={{ fontSize: 12, color: T.stone }}>
          共 {points.length} 个数据点，按填写时间排序
        </Text>
      )}
    </div>
  )
}
