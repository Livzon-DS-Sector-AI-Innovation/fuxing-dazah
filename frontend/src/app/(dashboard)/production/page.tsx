'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Row, Col, Tag, Typography, Spin, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  AppstoreOutlined,
  FileTextOutlined,
  ArrowRightOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  EditOutlined,
} from '@ant-design/icons'
import { getBatches } from '@/actions/production'
import { BatchStatus } from '@/types/production'
import Counter from '@/components/Counter'

const { Title, Text } = Typography

interface DashboardStats {
  totalBatches: number
  inProgressBatches: number
  completedBatches: number
  draftBatches: number
}

interface BatchRecord {
  id: string
  batch_no: string
  product_name?: string
  product_code: string
  status: string
}

const STAT_CARDS = [
  {
    key: 'total',
    title: '总批次',
    icon: <ExperimentOutlined />,
    bg: '#e6e0f5',
    iconColor: '#5645d4',
    valueColor: '#3a2a99',
    spotlightColor: 'rgba(86, 69, 212, 0.12)',
  },
  {
    key: 'inProgress',
    title: '执行中',
    icon: <SyncOutlined spin />,
    bg: '#ffe8d4',
    iconColor: '#dd5b00',
    valueColor: '#793400',
    spotlightColor: 'rgba(221, 91, 0, 0.12)',
  },
  {
    key: 'completed',
    title: '已完成',
    icon: <CheckCircleOutlined />,
    bg: '#d9f3e1',
    iconColor: '#1aae39',
    valueColor: '#1aae39',
    spotlightColor: 'rgba(26, 174, 57, 0.1)',
  },
  {
    key: 'draft',
    title: '草稿',
    icon: <EditOutlined />,
    bg: '#dcecfa',
    iconColor: '#0075de',
    valueColor: '#005bab',
    spotlightColor: 'rgba(0, 117, 222, 0.1)',
  },
]

const MENU_ITEMS = [
  {
    key: '/production/batches',
    title: '批次管理',
    description: '批次档案、状态流转与全链路溯源',
    icon: <AppstoreOutlined />,
    bg: '#e6e0f5',
    iconBg: '#5645d4',
  },
  {
    key: '/production/process',
    title: '产品工艺',
    description: '工艺规程主数据与版本管理',
    icon: <FileTextOutlined />,
    bg: '#ffe8d4',
    iconBg: '#dd5b00',
  },
]

/** 亮色主题聚光卡片 — 鼠标跟随径向渐变 */
function TintedSpotlightCard({
  bg,
  spotlightColor,
  children,
}: {
  bg: string
  spotlightColor: string
  children: React.ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: -999, y: -999 })
  const [opacity, setOpacity] = useState(0)

  const handleMove = useCallback((e: React.MouseEvent) => {
    if (!ref.current) return
    const r = ref.current.getBoundingClientRect()
    setPos({ x: e.clientX - r.left, y: e.clientY - r.top })
  }, [])

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      style={{
        position: 'relative',
        background: bg,
        borderRadius: 12,
        padding: '20px 24px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        cursor: 'default',
        overflow: 'hidden',
        transition: 'box-shadow 0.25s',
        boxShadow: opacity ? '0 4px 16px 0 rgba(15,15,15,0.1)' : undefined,
      }}
    >
      {/* Spotlight overlay */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          opacity,
          transition: 'opacity 0.3s ease',
          background: `radial-gradient(circle 280px at ${pos.x}px ${pos.y}px, ${spotlightColor}, transparent 80%)`,
        }}
      />
      {children}
    </div>
  )
}

export default function ProductionDashboard() {
  const router = useRouter()
  const [stats, setStats] = useState<DashboardStats>({
    totalBatches: 0,
    inProgressBatches: 0,
    completedBatches: 0,
    draftBatches: 0,
  })
  const [recentBatches, setRecentBatches] = useState<BatchRecord[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    try {
      const response = await getBatches({ page_size: 100 })
      if (response.code === 200) {
        const batches = response.data || []
        setStats({
          totalBatches: batches.length,
          inProgressBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.IN_PROGRESS).length,
          completedBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.COMPLETED).length,
          draftBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.DRAFT).length,
        })
        setRecentBatches(batches.slice(0, 5))
      }
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  const statValues: Record<string, number> = {
    total: stats.totalBatches,
    inProgress: stats.inProgressBatches,
    completed: stats.completedBatches,
    draft: stats.draftBatches,
  }

  const getStatusTag = (status: string) => {
    const map: Record<string, { color: string; label: string }> = {
      draft: { color: 'default', label: '草稿' },
      released: { color: 'blue', label: '已下达' },
      in_progress: { color: 'processing', label: '执行中' },
      completed: { color: 'success', label: '已完成' },
      cancelled: { color: 'error', label: '已取消' },
    }
    const c = map[status] ?? { color: 'default', label: status }
    return (
      <Tag
        color={c.color}
        className={status === 'in_progress' ? 'tag-production-active' : undefined}
      >
        {c.label}
      </Tag>
    )
  }

  const recentColumns: ColumnsType<BatchRecord> = [
    {
      title: '批次号',
      dataIndex: 'batch_no',
      render: (v: string) => <Text strong style={{ fontSize: 13 }}>{v}</Text>,
    },
    {
      title: '产品',
      dataIndex: 'product_name',
      render: (v: string) => <Text style={{ color: '#5d5b54', fontSize: 13 }}>{v || '—'}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => getStatusTag(s),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* ── Header ── */}
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0, fontSize: 22, fontWeight: 600, color: '#1a1a1a' }}>
          生产管理概览
        </Title>
        <Text style={{ color: '#787671', fontSize: 14 }}>实时监控生产运营状态，快速进入管理视图</Text>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
          <Spin size="large" />
        </div>
      ) : (
        <>
          {/* ── Stats Row ── */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            {STAT_CARDS.map(s => (
              <Col span={6} key={s.key}>
                <TintedSpotlightCard bg={s.bg} spotlightColor={s.spotlightColor}>
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 10,
                      background: '#fff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 20,
                      color: s.iconColor,
                      flexShrink: 0,
                      zIndex: 1,
                    }}
                  >
                    {s.icon}
                  </div>
                  <div style={{ zIndex: 1 }}>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 2 }}>
                      {s.title}
                    </div>
                    <Counter
                      value={statValues[s.key]}
                      fontSize={36}
                      padding={0}
                      gap={2}
                      textColor={s.valueColor}
                      fontWeight={600}
                      borderRadius={4}
                      horizontalPadding={0}
                      gradientHeight={0}
                    />
                  </div>
                </TintedSpotlightCard>
              </Col>
            ))}
          </Row>

          {/* ── Quick Access + Recent ── */}
          <Row gutter={24}>
            <Col span={14}>
              <Card
                title={<Text strong style={{ fontSize: 15 }}>快捷操作</Text>}
                variant="borderless"
                style={{ height: '100%' }}
              >
                <Row gutter={[16, 16]}>
                  {MENU_ITEMS.map(item => (
                    <Col span={12} key={item.key}>
                      <div
                        onClick={() => router.push(item.key)}
                        style={{
                          background: item.bg,
                          borderRadius: 12,
                          padding: '20px 24px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 16,
                          transition: 'box-shadow 0.2s, transform 0.15s',
                          border: '1px solid transparent',
                        }}
                        onMouseEnter={e => {
                          e.currentTarget.style.boxShadow = '0 4px 12px 0 rgba(15,15,15,0.1)'
                          e.currentTarget.style.transform = 'translateY(-1px)'
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.boxShadow = ''
                          e.currentTarget.style.transform = ''
                        }}
                      >
                        <div
                          style={{
                            width: 44,
                            height: 44,
                            borderRadius: 10,
                            background: item.iconBg,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: 20,
                            color: '#fff',
                            flexShrink: 0,
                          }}
                        >
                          {item.icon}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: 15, color: '#1a1a1a', marginBottom: 2 }}>
                            {item.title}
                          </div>
                          <div style={{ fontSize: 13, color: '#5d5b54' }}>
                            {item.description}
                          </div>
                        </div>
                        <ArrowRightOutlined style={{ color: '#a4a097', fontSize: 14 }} />
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>

            <Col span={10}>
              <Card
                title={<Text strong style={{ fontSize: 15 }}>最近批次</Text>}
                variant="borderless"
                style={{ height: '100%' }}
                extra={
                  <a
                    onClick={() => router.push('/production/batches')}
                    style={{ fontSize: 13, color: '#0075de' }}
                  >
                    查看全部
                  </a>
                }
              >
                {recentBatches.length > 0 ? (
                  <Table
                    columns={recentColumns}
                    dataSource={recentBatches}
                    rowKey="id"
                    size="small"
                    pagination={false}
                    onRow={() => ({
                      onClick: () => router.push('/production/batches'),
                      style: { cursor: 'pointer' },
                    })}
                  />
                ) : (
                  <div style={{ textAlign: 'center', padding: '48px 0', color: '#787671', fontSize: 14 }}>
                    暂无批次数据
                  </div>
                )}
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  )
}
