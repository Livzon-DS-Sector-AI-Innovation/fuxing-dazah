'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Row, Col, Typography, Spin } from 'antd'
import {
  AppstoreOutlined,
  FileTextOutlined,
  ArrowRightOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  EditOutlined,
  ToolOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import { getBatches } from '@/actions/production'
import { BatchStatus } from '@/types/production'
import type { Product } from '@/types/production'
import { fetchProductsClient } from '@/lib/api/production-client'
import Counter from '@/components/Counter'
import { StepCyclePanel } from '@/components/production'

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
  {
    key: '/production/workbench',
    title: '工作台',
    description: '批次执行与工序现场操作',
    icon: <ToolOutlined />,
    bg: '#dcecfa',
    iconBg: '#0075de',
  },
  {
    key: '/production/analytics',
    title: '数据汇总',
    description: '工段汇总矩阵与批次字段趋势分析',
    icon: <BarChartOutlined />,
    bg: '#d9f3e1',
    iconBg: '#1aae39',
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
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
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
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  // 页面加载时获取数据
  useEffect(() => {
    const load = async () => {
      try {
        const [batchRes, prods] = await Promise.all([
          getBatches({ page_size: 100 }),
          fetchProductsClient(),
        ])
        if (batchRes.code === 200) {
          const batches = batchRes.data || []
          setStats({
            totalBatches: batches.length,
            inProgressBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.IN_PROGRESS).length,
            completedBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.COMPLETED).length,
            draftBatches: batches.filter((b: BatchRecord) => b.status === BatchStatus.DRAFT).length,
          })
        }
        setProducts(prods)
      } catch (error) {
        console.error('Failed to load dashboard data:', error)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const statValues: Record<string, number> = {
    total: stats.totalBatches,
    inProgress: stats.inProgressBatches,
    completed: stats.completedBatches,
    draft: stats.draftBatches,
  }

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ marginBottom: 16 }}>
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
          <Row gutter={12} style={{ marginBottom: 16 }}>
            {STAT_CARDS.map(s => (
              <Col span={6} key={s.key}>
                <TintedSpotlightCard bg={s.bg} spotlightColor={s.spotlightColor}>
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 8,
                      background: '#fff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 16,
                      color: s.iconColor,
                      flexShrink: 0,
                      zIndex: 1,
                    }}
                  >
                    {s.icon}
                  </div>
                  <div style={{ zIndex: 1 }}>
                    <div style={{ fontSize: 12, color: '#5d5b54', marginBottom: 2 }}>
                      {s.title}
                    </div>
                    <Counter
                      value={statValues[s.key]}
                      fontSize={24}
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

          {/* ── Quick Access ── */}
          <Row gutter={24}>
            <Col span={24}>
              <Card
                title={<Text strong style={{ fontSize: 15 }}>快捷操作</Text>}
                variant="borderless"
              >
                <Row gutter={[12, 12]}>
                  {MENU_ITEMS.map(item => (
                    <Col xs={12} lg={6} key={item.key}>
                      <div
                        onClick={() => router.push(item.key)}
                        style={{
                          background: item.bg,
                          borderRadius: 12,
                          padding: '14px 18px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
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
                            width: 36,
                            height: 36,
                            borderRadius: 8,
                            background: item.iconBg,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: 17,
                            color: '#fff',
                            flexShrink: 0,
                          }}
                        >
                          {item.icon}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: 14, color: '#1a1a1a', marginBottom: 2 }}>
                            {item.title}
                          </div>
                          <div style={{ fontSize: 12, color: '#5d5b54' }}>
                            {item.description}
                          </div>
                        </div>
                        <ArrowRightOutlined style={{ color: '#a4a097', fontSize: 13 }} />
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>
          </Row>

          {/* ── 工序周期分析 ── */}
          <StepCyclePanel products={products} />
        </>
      )}
    </div>
  )
}
