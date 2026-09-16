'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, Table, Select, DatePicker, Space, App, Tag, Typography } from 'antd'
import { Line } from '@ant-design/charts'
import type { SummaryMatrix, SummaryMatrixRow, SummaryTrend } from '@/types/quality'
import { fetchSummaryMatrix, fetchSummaryProducts, fetchItemTrend } from '@/actions/quality'

const { Text } = Typography
const { RangePicker } = DatePicker

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  completed: { label: '已完成', color: 'success' },
  pending_review: { label: '待复核', color: 'warning' },
}

export default function SummaryView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [matrix, setMatrix] = useState<SummaryMatrix | null>(null)
  const [products, setProducts] = useState<string[]>([])
  const [selectedProduct, setSelectedProduct] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)

  // 趋势分析：选项目 → 跨批次数值序列
  const [trendItem, setTrendItem] = useState<string | undefined>()
  const [trend, setTrend] = useState<SummaryTrend | null>(null)
  const [trendLoading, setTrendLoading] = useState(false)

  useEffect(() => {
    if (!trendItem) { setTrend(null); return }
    setTrendLoading(true)
    fetchItemTrend(trendItem, selectedProduct)
      .then((res) => setTrend(res.data))
      .catch((err: any) => message.error(err.message || '获取趋势失败'))
      .finally(() => setTrendLoading(false))
  }, [trendItem, selectedProduct, message])

  useEffect(() => {
    fetchSummaryProducts().then(setProducts).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSummaryMatrix(
        selectedProduct,
        dateRange?.[0],
        dateRange?.[1],
      )
      setMatrix(res.data)
    } catch (err: any) {
      message.error(err.message || '加载汇总失败')
    } finally {
      setLoading(false)
    }
  }, [selectedProduct, dateRange, message])

  useEffect(() => { load() }, [load])

  // 矩阵列：批次信息 + 全部检验项目横向逐一列出
  const columns = [
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', width: 220, fixed: 'left' as const, ellipsis: true },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 140, fixed: 'left' as const },
    { title: '生产日期', dataIndex: 'production_date', key: 'production_date', width: 110, render: (v: string | null) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        const meta = STATUS_LABEL[v]
        return meta ? <Tag color={meta.color}>{meta.label}</Tag> : v
      } },
    { title: '判定', dataIndex: 'all_pass', key: 'all_pass', width: 80,
      render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '合格' : '不合格'}</Tag> },
    ...(matrix?.columns || []).map((item) => ({
      title: item,
      key: item,
      width: 130,
      render: (_: unknown, r: SummaryMatrixRow) => {
        const cell = r.cells[item]
        if (!cell) return <Text type="secondary">-</Text>
        return (
          <Text style={{ color: cell.is_pass ? undefined : '#ff4d4f' }}>
            {cell.value}{cell.unit}
          </Text>
        )
      },
    })),
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="全部产品"
          allowClear
          value={selectedProduct}
          onChange={setSelectedProduct}
          options={products.map(p => ({ value: p, label: p }))}
          style={{ width: 240 }}
        />
        <RangePicker
          onChange={(_, dateStrings) => {
            setDateRange(dateStrings[0] && dateStrings[1] ? dateStrings as [string, string] : null)
          }}
        />
      </Space>

      <Card size="small" title={`QC 汇总表（${matrix?.rows.length ?? 0} 个批次，检验项目横向列出）`}>
        <Table
          rowKey="task_id"
          columns={columns}
          dataSource={matrix?.rows || []}
          loading={loading}
          size="small"
          pagination={false}
          scroll={{ x: 400 + (matrix?.columns.length || 0) * 130, y: 480 }}
        />
      </Card>

      <Card size="small" title="趋势分析（项目跨批次走势，限度参考线）">
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            placeholder="选择检验项目查看趋势"
            allowClear
            showSearch
            value={trendItem}
            onChange={setTrendItem}
            options={(matrix?.columns || []).map((c) => ({ value: c, label: c }))}
            style={{ width: 260 }}
          />
          {trend?.standard_text && (
            <Text type="secondary">标准：{trend.standard_text}</Text>
          )}
        </Space>
        {trend && trend.points.length >= 2 ? (
          <Line
            height={260}
            loading={trendLoading}
            data={trend.points.map((p) => ({
              batch: p.batch_number,
              value: p.value,
              pass: p.is_pass,
              limit_max: trend.limit_max,
              limit_min: trend.limit_min,
            }))}
            xField="batch"
            yField="value"
            xAxis={{
              label: { autoRotate: true, style: { fontSize: 11, fill: '#a4a097' } },
              grid: null,
              tickLine: null,
            }}
            yAxis={{
              grid: { line: { style: { stroke: '#f0f0f0', lineDash: [3, 3] } } },
              label: { style: { fontSize: 11, fill: '#a4a097' } },
            }}
            tooltip={{
              crosshairs: { type: 'xy' as const },
              items: [
                { channel: 'y', valueFormatter: (v: number) => `${v}${trend.unit}` },
                {
                  channel: 'y',
                  field: 'pass',
                  valueFormatter: (v: boolean) => (v ? '合格' : '不合格'),
                },
              ],
            }}
            annotations={[
              ...(trend.limit_max != null
                ? [{ type: 'lineY', yField: 'limit_max', style: { stroke: '#d03b3b', lineDash: [4, 4], lineWidth: 1 } }]
                : []),
              ...(trend.limit_min != null
                ? [{ type: 'lineY', yField: 'limit_min', style: { stroke: '#0ca30c', lineDash: [4, 4], lineWidth: 1 } }]
                : []),
            ]}
            style={{ lineWidth: 2 }}
            point={{ size: 4, shape: 'circle', style: (d: any) => ({ fill: d.pass ? '#0ca30c' : '#d03b3b', stroke: '#fff', lineWidth: 1 }) }}
            color="#6b6b6b"
          />
        ) : (
          <Text type="secondary">
            {trendItem ? '该项目数值批次不足 2 批，无法绘制趋势' : '请先选择检验项目'}
          </Text>
        )}
      </Card>
    </div>
  )
}
