'use client'

import { useEffect, useMemo, useState } from 'react'
import { Card, Table, Tag, Typography, Alert, Select, Space, Empty, Skeleton } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { BarChartOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { fetchStepCycleClient } from '@/lib/api/production-client'
import type { StepCycleStat, Product } from '@/types/production'
import { stageColor } from '@/components/production/shared/stageColor'
import styles from './StepCyclePanel.module.css'

const { Text } = Typography

interface StepCycleRouteGroup {
  key: string
  routeName: string
  steps: StepCycleStat[]
  totalHours: number
  totalSamples: number
}

function fmtHours(h: number | null): string {
  if (h == null) return '—'
  if (h < 1) return `${Math.round(h * 60)} 分钟`
  return `${h.toFixed(1)} 小时`
}

function buildColumns(totalHours: number): ColumnsType<StepCycleStat> {
  return [
    {
      title: '#',
      dataIndex: 'sort_order',
      width: 48,
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
      width: 100,
      render: (v: string) => <Tag color={stageColor(v)}>{v}</Tag>,
    },
    {
      title: '平均耗时',
      dataIndex: 'avg_hours',
      width: 128,
      render: (_: number, r: StepCycleStat) => (
        <Space size={6}>
          <ClockCircleOutlined style={{ color: '#5645d4', fontSize: 13 }} />
          <Text strong style={{ color: '#5645d4' }}>{fmtHours(r.avg_hours)}</Text>
        </Space>
      ),
    },
    {
      title: '耗时占比',
      dataIndex: 'avg_hours',
      width: 190,
      render: (_: number, r: StepCycleStat) => {
        const pct = totalHours > 0 ? (r.avg_hours / totalHours) * 100 : 0
        const color = stageColor(r.stage_name)
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className={styles.barTrack}>
              <div
                className={styles.barFill}
                style={{ width: `${Math.max(pct, pct > 0 ? 2 : 0)}%`, background: color }}
              />
            </div>
            <Text style={{ width: 38, flexShrink: 0, color: '#787671', fontSize: 11, textAlign: 'right' }}>
              {pct.toFixed(0)}%
            </Text>
          </div>
        )
      },
    },
    {
      title: '最短',
      dataIndex: 'min_hours',
      width: 104,
      render: (v: number | null) => <Text type="secondary">{fmtHours(v)}</Text>,
    },
    {
      title: '最长',
      dataIndex: 'max_hours',
      width: 104,
      render: (v: number | null) => <Text type="secondary">{fmtHours(v)}</Text>,
    },
    {
      title: '样本数',
      dataIndex: 'n',
      width: 76,
      render: (v: number) => (
        <Text type={v < 30 ? 'warning' : 'secondary'} style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
  ]
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
  const [days, setDays] = useState(30)

  // 渲染期间派生实际值：用户选了什么就用什么，没选就取第一个
  const selectedProduct = useMemo(
    () => productOverride ?? (products.length > 0 ? products[0].id : undefined),
    [productOverride, products],
  )
  // 加载统计数据
  useEffect(() => {
    let cancelled = false
    if (!selectedProduct) return () => { cancelled = true }

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetchStepCycleClient({
          product_id: selectedProduct,
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
  }, [selectedProduct, days])

  const routeGroups = useMemo<StepCycleRouteGroup[]>(() => {
    const groups = new Map<string, StepCycleRouteGroup>()
    for (const step of data) {
      const key = step.route_id || step.route_name || 'unknown-route'
      const existing = groups.get(key)
      if (existing) {
        existing.steps.push(step)
        existing.totalHours += step.avg_hours
        existing.totalSamples += step.n
      } else {
        groups.set(key, {
          key,
          routeName: step.route_name || '未命名工艺路径',
          steps: [step],
          totalHours: step.avg_hours,
          totalSamples: step.n,
        })
      }
    }
    return [...groups.values()]
  }, [data])

  const isEmpty = !loading && data.length === 0
  const selectedProductName = products.find(p => p.id === selectedProduct)?.product_name

  return (
    <Card
      className={styles.panel}
      title={
        <div className={styles.title}>
          <span className={styles.titleIcon}><BarChartOutlined /></span>
          <span>
            <span className={styles.titleText}>工序周期分析</span>
            <span className={styles.titleSubtext}>已发布路径 · 含前版本血缘样本</span>
          </span>
        </div>
      }
      extra={
        <div className={styles.controls}>
          <Select
            className={styles.productSelect}
            placeholder="选择产品"
            value={selectedProduct}
            onChange={setProductOverride}
            options={products.map(p => ({ label: p.product_name, value: p.id }))}
          />
          <Select
            className={styles.daysSelect}
            value={days}
            onChange={setDays}
            options={[
              { label: '最近 7 天', value: 7 },
              { label: '最近 30 天', value: 30 },
              { label: '最近 90 天', value: 90 },
            ]}
          />
        </div>
      }
      variant="borderless"
    >
      {selectedProduct && (
        <div className={styles.scopeBar}>
          <span className={styles.scopeLead}>
            <span className={styles.scopeDot} />
            分析产品 <strong>{selectedProductName ?? '当前产品'}</strong>
          </span>
          <span className={styles.scopeMeta}>
            {routeGroups.length} 条工艺路径 · {data.length} 道工序 · 涵盖 {totalBatches} 个批次
          </span>
        </div>
      )}

      {selectedProduct && error && (
        <Alert
          message={error}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}
      {selectedProduct && sampleNote && (
        <Alert
          title={sampleNote}
          type={sampleNote.includes('暂无') ? 'info' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {!selectedProduct ? (
        <div className={styles.emptyState}>
          <Empty
            description="请选择产品查看工序周期"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      ) : isEmpty ? (
        <div className={styles.emptyState}>
          <Empty
            description="暂无工序执行记录，开始生产后这里将展示各工序的耗时统计"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      ) : loading && routeGroups.length === 0 ? (
        <div className={styles.loadingState}>
          <Skeleton active paragraph={{ rows: 5 }} />
        </div>
      ) : (
        routeGroups.map((group, index) => (
          <section className={styles.routeGroup} key={group.key}>
            <div className={styles.routeHeader}>
              <span className={styles.routeMark}>{String(index + 1).padStart(2, '0')}</span>
              <span className={styles.routeName}>{group.routeName}</span>
              <div className={styles.routeMeta}>
                <span>{group.steps.length} 道工序</span>
                <span>·</span>
                <span>样本 {group.totalSamples}</span>
                <span>·</span>
                <span>平均总耗时 <span className={styles.routeTotal}>{fmtHours(group.totalHours)}</span></span>
              </div>
            </div>
            <div className={styles.tableWrap}>
              <Table
                columns={buildColumns(group.totalHours)}
                dataSource={group.steps}
                rowKey="node_id"
                loading={loading}
                size="middle"
                pagination={false}
                summary={() => (
                  <Table.Summary.Row>
                    <Table.Summary.Cell index={0} colSpan={3}>
                      <Text strong>路径平均总耗时</Text>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={1}>
                      <Text strong style={{ color: '#5645d4' }}>
                        {fmtHours(group.totalHours)}
                      </Text>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={2} colSpan={4} />
                  </Table.Summary.Row>
                )}
              />
            </div>
          </section>
        ))
      )}
    </Card>
  )
}
