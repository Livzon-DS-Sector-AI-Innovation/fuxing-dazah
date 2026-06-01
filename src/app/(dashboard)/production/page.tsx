'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Card,
  Row,
  Col,
  Statistic,
  Tag,
  Typography,
  Space,
  Spin,
  Table,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  AppstoreOutlined,
  ProjectOutlined,
  FileTextOutlined,
  HistoryOutlined,
  BarChartOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { getBatches } from '@/actions/production'
import { BatchStatus } from '@/types/production'

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

const menuItems = [
  {
    key: '/production/batches',
    title: '批次管理',
    description: '批次档案管理、状态流转',
    icon: <AppstoreOutlined />,
    color: '#5645d4',
  },
  {
    key: '/production/plan',
    title: '生产计划',
    description: '月/周生产排程管理',
    icon: <ProjectOutlined />,
    color: '#1aae39',
  },
  {
    key: '/production/process',
    title: '工艺规程',
    description: '工艺规程主数据、版本管理',
    icon: <FileTextOutlined />,
    color: '#dd5b00',
  },
  {
    key: '/production/records',
    title: '生产记录',
    description: '电子批记录、操作日志',
    icon: <HistoryOutlined />,
    color: '#e03131',
  },
  {
    key: '/production/balance',
    title: '物料平衡',
    description: '投入产出平衡计算',
    icon: <BarChartOutlined />,
    color: '#8b5cf6',
  },
]

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

  const getStatusTag = (status: string) => {
    const statusMap: Record<string, { color: string; label: string }> = {
      draft: { color: 'default', label: '草稿' },
      released: { color: 'blue', label: '已下达' },
      in_progress: { color: 'processing', label: '执行中' },
      completed: { color: 'success', label: '已完成' },
      cancelled: { color: 'error', label: '已取消' },
    }
    const config = statusMap[status] || { color: 'default', label: status }
    return <Tag color={config.color}>{config.label}</Tag>
  }

  const recentColumns: ColumnsType<BatchRecord> = [
    {
      title: '批次号',
      dataIndex: 'batch_no',
      key: 'batch_no',
      render: (text: string) => <Text>{text}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => getStatusTag(status),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <Title level={4} className="mb-1">生产管理概览</Title>
        <Text type="secondary">实时监控生产运营状态</Text>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Spin size="large" />
        </div>
      ) : (
        <>
          {/* Statistics Cards */}
          <Row gutter={16}>
            <Col span={6}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="总批次"
                  value={stats.totalBatches}
                  styles={{ content: { color: '#5645d4' } }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="执行中"
                  value={stats.inProgressBatches}
                  styles={{ content: { color: '#dd5b00' } }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="已完成"
                  value={stats.completedBatches}
                  styles={{ content: { color: '#1aae39' } }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="草稿"
                  value={stats.draftBatches}
                  styles={{ content: { color: '#787671' } }}
                />
              </Card>
            </Col>
          </Row>

          {/* Quick Links and Recent Batches */}
          <Row gutter={24}>
            <Col span={14}>
              <Card
                title="快速入口"
                variant="borderless"
                className="shadow-sm h-full"
              >
                <Row gutter={[16, 16]}>
                  {menuItems.map((item) => (
                    <Col span={12} key={item.key}>
                      <div
                        className="p-4 rounded-lg border border-[var(--color-hairline)] hover:border-[var(--color-primary)] cursor-pointer transition-colors"
                        onClick={() => router.push(item.key)}
                      >
                        <Space align="start">
                          <div
                            className="w-10 h-10 rounded-lg flex items-center justify-center text-white text-lg"
                            style={{ backgroundColor: item.color }}
                          >
                            {item.icon}
                          </div>
                          <div>
                            <Text strong className="block">{item.title}</Text>
                            <Text type="secondary" className="text-xs">
                              {item.description}
                            </Text>
                          </div>
                          <ArrowRightOutlined className="text-[var(--color-muted)] ml-auto" />
                        </Space>
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>

            <Col span={10}>
              <Card
                title="最近批次"
                variant="borderless"
                className="shadow-sm h-full"
                extra={
                  <a onClick={() => router.push('/production/batches')}>查看全部</a>
                }
              >
                {recentBatches.length > 0 ? (
                  <Table
                    columns={recentColumns}
                    dataSource={recentBatches}
                    rowKey="id"
                    size="small"
                    pagination={false}
                    className="cursor-pointer"
                    onRow={(record) => ({
                      onClick: () => router.push('/production/batches'),
                    })}
                  />
                ) : (
                  <div className="text-center py-8 text-[var(--color-muted)]">
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
