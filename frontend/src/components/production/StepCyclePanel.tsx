'use client'

import { useEffect, useMemo, useState } from 'react'
import { Card, Table, Tag, Typography, Alert, Select, Space, Empty } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { BarChartOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { fetchStepCycleClient, fetchRoutesClient } from '@/lib/api/production-client'
import type { StepCycleStat, Product, ProcessRoute } from '@/types/production'
import { stageColor } from '@/components/production/shared/stageColor'

const { Text } = Typography

function fmtHours(h: number | null): string {
  if (h == null) return '—'
  if (h < 1) return `${Math.round(h * 60)} 分钟`
  return `${h.toFixed(1)} 小时`
}

interface Props {
  products: Product[]
}

export default function StepCyclePanel({ products }: Props) {
  const [data, setData] = useState<StepCycleStat[]>([])
  const [totalBatches, setTotalBatches] = useState(0)
  const [sampleNote, setSampleNote] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 用户手动选择的覆盖值，undefined = 自动选第一个
  const [productOverride, setProductOverride] = useState<string | undefined>()
  const [routeOverride, setRouteOverride] = useState<string | undefined>()
  const [routes, setRoutes] = useState<ProcessRoute[]>([])
  const [days, setDays] = useState(30)

  // 渲染期间派生实际值：用户选了什么就用什么，没选就取第一个
  const selectedProduct = useMemo(
    () => productOverride ?? (products.length > 0 ? products[0].id : undefined),
    [productOverride, products],
  )
  const selectedRoute = useMemo(
    () => routeOverride ?? (routes.length > 0 ? routes[0].id : undefined),
    [routeOverride, routes],
  )

  // 产品变化时加载路线（外部系统调用，effect 合理）
  useEffect(() => {
    if (!selectedProduct) return
    fetchRoutesClient(selectedProduct).then(setRoutes).catch(() => setRoutes([]))
  }, [selectedProduct])

  // 加载统计数据
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetchStepCycleClient({
          route_id: selectedRoute || undefined,
          product_id: !selectedRoute ? selectedProduct || undefined : undefined,
          days,
        })
        if (cancelled) return
        setData(res.steps)
        setTotalBatches(res.total_batches)
        setSampleNote(res.sample_note)
      } catch {
        if (cancelled) return
        setData([])
        setTotalBatches(0)
        setSampleNote(null)
        setError('获取工序周期数据失败，请稍后重试')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [selectedProduct, selectedRoute, days])

  const columns: ColumnsType<StepCycleStat> = [
    {
      title: '#',
      dataIndex: 'sort_order',
      width: 40,
      render: (v: number) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '工序',
      dataIndex: 'node_name',
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '工段',
      dataIndex: 'stage_name',
      width: 80,
      render: (v: string) => <Tag color={stageColor(v)}>{v}</Tag>,
    },
    {
      title: '平均耗时',
      dataIndex: 'avg_hours',
      width: 120,
      render: (_: number, r: StepCycleStat) => (
        <Space>
          <ClockCircleOutlined style={{ color: '#1677ff', fontSize: 13 }} />
          <Text strong style={{ color: '#1677ff' }}>{fmtHours(r.avg_hours)}</Text>
        </Space>
      ),
    },
    {
      title: '占比',
      dataIndex: 'avg_hours',
      width: 160,
      render: (_: number, r: StepCycleStat) => {
        const pct = totalHours > 0 ? (r.avg_hours / totalHours) * 100 : 0
        const color = stageColor(r.stage_name)
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              flex: 1, height: 14, background: '#f0f0ed', borderRadius: 3, overflow: 'hidden',
            }}>
              <div style={{
                width: `${Math.max(pct, 1)}%`, height: '100%',
                background: color, borderRadius: 3, transition: 'width 0.3s ease',
              }} />
            </div>
            <Text style={{ fontSize: 11, color: '#787671', width: 38, textAlign: 'right', flexShrink: 0 }}>
              {pct.toFixed(0)}%
            </Text>
          </div>
        )
      },
    },
    {
      title: '最短',
      dataIndex: 'min_hours',
      width: 100,
      render: (v: number | null) => <Text type="secondary">{fmtHours(v)}</Text>,
    },
    {
      title: '最长',
      dataIndex: 'max_hours',
      width: 100,
      render: (v: number | null) => <Text type="secondary">{fmtHours(v)}</Text>,
    },
    {
      title: '样本数',
      dataIndex: 'n',
      width: 70,
      render: (v: number) => (
        <Text type={v < 30 ? 'warning' : 'secondary'} style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
  ]

  const totalHours = data.reduce((s, r) => s + r.avg_hours, 0)
  const isEmpty = !loading && data.length === 0

  return (
    <Card
      title={
        <Space>
          <BarChartOutlined />
          <span>工序周期分析</span>
          {totalBatches > 0 && (
            <Tag style={{ marginLeft: 8 }}>涉及 {totalBatches} 个批次</Tag>
          )}
        </Space>
      }
      extra={
        <Space>
          <Select
            allowClear
            placeholder="全部产品"
            style={{ width: 160 }}
            value={selectedProduct}
            onChange={v => { setProductOverride(v); setRouteOverride(undefined) }}
            options={products.map(p => ({ label: p.product_name, value: p.id }))}
          />
          <Select
            allowClear
            placeholder="全部路线"
            style={{ width: 150 }}
            value={selectedRoute}
            onChange={setRouteOverride}
            disabled={!selectedProduct || routes.length === 0}
            options={routes.map(r => ({ label: r.route_name, value: r.id }))}
          />
          <Select
            style={{ width: 120 }}
            value={days}
            onChange={setDays}
            options={[
              { label: '最近 7 天', value: 7 },
              { label: '最近 30 天', value: 30 },
              { label: '最近 90 天', value: 90 },
            ]}
          />
        </Space>
      }
      variant="borderless"
      style={{ marginTop: 24 }}
    >
      {error && (
        <Alert
          message={error}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}
      {sampleNote && (
        <Alert
          title={sampleNote}
          type={sampleNote.includes('暂无') ? 'info' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {isEmpty ? (
        <Empty
          description="暂无工序执行记录，开始生产后这里将展示各工序的耗时统计"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <Table
          columns={columns}
          dataSource={data}
          rowKey="node_id"
          loading={loading}
          size="middle"
          pagination={false}
          summary={() =>
            data.length > 0 ? (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={3}>
                  <Text strong>合计</Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={1}>
                  <Text strong style={{ color: '#1677ff' }}>
                    {fmtHours(totalHours)}
                  </Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={2} colSpan={5} />
              </Table.Summary.Row>
            ) : null
          }
        />
      )}

    </Card>
  )
}
