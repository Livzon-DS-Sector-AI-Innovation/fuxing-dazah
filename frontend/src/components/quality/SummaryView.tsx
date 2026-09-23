'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Table, Select, DatePicker, Space, App, Tag, Typography, Button, Switch, theme } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DownloadOutlined } from '@ant-design/icons'
import type { SummaryMatrix, SummaryMatrixRow, SummaryTrend } from '@/types/quality'
import { fetchSummaryMatrix, fetchSummaryProducts, fetchItemTrend, exportSummaryMatrix } from '@/actions/quality'
import TrendChart from './TrendChart'

const { Text } = Typography
const { RangePicker } = DatePicker

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  completed: { label: '已完成', color: 'success' },
  pending_review: { label: '待复核', color: 'warning' },
  in_progress: { label: '填报中', color: 'processing' },
}


export default function SummaryView() {
  const router = useRouter()
  const { token } = theme.useToken()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [matrix, setMatrix] = useState<SummaryMatrix | null>(null)
  const [products, setProducts] = useState<string[]>([])
  const [selectedProduct, setSelectedProduct] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [includeInProgress, setIncludeInProgress] = useState(false)

  // 趋势分析：选项目 → 跨批次数值序列
  const [trendItem, setTrendItem] = useState<string | undefined>()
  const [trend, setTrend] = useState<SummaryTrend | null>(null)
  const [trendLoading, setTrendLoading] = useState(false)
  const [trendError, setTrendError] = useState<string | null>(null)
  const [trendReloadKey, setTrendReloadKey] = useState(0)

  useEffect(() => {
    fetchSummaryProducts().then(setProducts).catch(() => message.warning('产品列表加载失败，请刷新重试'))
  }, [message])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSummaryMatrix(
        selectedProduct,
        dateRange?.[0],
        dateRange?.[1],
        includeInProgress,
      )
      setMatrix(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载汇总失败')
    } finally {
      setLoading(false)
    }
  }, [selectedProduct, dateRange, includeInProgress, message])

  useEffect(() => { (async () => { await load() })() }, [load])

  useEffect(() => {
    (async () => {
      if (!trendItem) { setTrend(null); setTrendError(null); return }
      setTrendLoading(true)
      setTrendError(null)
      fetchItemTrend(trendItem, selectedProduct)
        .then((res) => setTrend(res.data))
        .catch((err: unknown) => setTrendError((err instanceof Error ? err.message : String(err)) || '获取趋势失败'))
        .finally(() => setTrendLoading(false))
    })()
  }, [trendItem, selectedProduct, trendReloadKey])

  const handleExport = async () => {
    try {
      const blob = await exportSummaryMatrix(
        selectedProduct,
        dateRange?.[0],
        dateRange?.[1],
        includeInProgress,
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'QC汇总表.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '导出失败')
    }
  }

  // 矩阵列：SOP 分组二级表头 + 批次信息列固定左侧
  const matrixColumns = useMemo(() => {
    const base = [
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
    ]
  // 单元格渲染（组件内定义：取主题 token 色值，不合格标红）
  function renderCell(item: string) {
    return function CellRenderer(_: unknown, r: SummaryMatrixRow) {
      const cell = r.cells[item]
      if (!cell) return <Text type="secondary">-</Text>
      return (
        <Text style={{ color: cell.is_pass ? undefined : token.colorError }}>
          {cell.value}{cell.unit}
        </Text>
      )
    }
  }

    const cols = matrix?.columns || []
    const groups: ColumnsType<SummaryMatrixRow> = []
    const bySop = new Map<string, ColumnsType<SummaryMatrixRow>>()
    const order: string[] = []
    for (const c of cols) {
      const key = c.sop_no || ''
      if (!bySop.has(key)) { bySop.set(key, []); order.push(key) }
      bySop.get(key)!.push({ title: c.name, key: c.name, width: 130, render: renderCell(c.name) })
    }
    for (const key of order) {
      const children = bySop.get(key)!
      if (children.length === 1) {
        groups.push(children[0])
      } else {
        groups.push({ title: key || '其他', children })
      }
    }
    return [...base, ...groups]
  }, [matrix, token.colorError])

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
        <Switch
          checked={includeInProgress}
          onChange={setIncludeInProgress}
          checkedChildren="含填报中"
          unCheckedChildren="仅已完成"
        />
        <Button icon={<DownloadOutlined />} onClick={handleExport}>导出 Excel</Button>
      </Space>

      <Card size="small" title={`QC 汇总表（${matrix?.rows.length ?? 0} 个批次，检验项目横向列出，按 SOP 分组）`}>
        <Table
          rowKey="task_id"
          columns={matrixColumns}
          dataSource={matrix?.rows || []}
          loading={loading}
          size="small"
          pagination={false}
          scroll={{ x: 400 + (matrix?.columns.length || 0) * 130, y: 480 }}
          onRow={(r: SummaryMatrixRow) => ({
            style: { cursor: 'pointer' },
            onClick: () => router.push(`/quality/task/${r.task_id}`),
          })}
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
            options={(matrix?.columns || []).map((c) => ({ value: c.name, label: c.name }))}
            style={{ width: 260 }}
          />
          {trend?.standard_text && (
            <Text type="secondary">标准：{trend.standard_text}</Text>
          )}
        </Space>
        {trendError ? (
          <Space>
            <Text type="danger">{trendError}</Text>
            <Button size="small" onClick={() => setTrendReloadKey((k) => k + 1)}>重试</Button>
          </Space>
        ) : trend && trend.points.length >= 2 ? (
          <TrendChart trend={trend} />
        ) : (
          <Text type="secondary">
            {trendItem ? (trendLoading ? '加载中…' : '该项目数值批次不足 2 批，无法绘制趋势') : '请先选择检验项目'}
          </Text>
        )}
      </Card>
    </div>
  )
}
