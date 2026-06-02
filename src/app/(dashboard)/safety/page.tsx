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
} from 'antd'
import {
  SafetyOutlined,
  WarningOutlined,
  AlertOutlined,
  BookOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { getChecks, getHazards, getAccidents, getTrainings } from '@/actions/safety'

const { Title, Text } = Typography

interface DashboardStats {
  totalChecks: number
  pendingChecks: number
  openHazards: number
  overdueHazards: number
  recentAccidents: number
  upcomingTrainings: number
}

const menuItems = [
  {
    key: '/safety/check',
    title: '安全检查',
    description: '日常/专项安全检查记录管理',
    icon: <SafetyOutlined />,
    color: '#1aae39',
  },
  {
    key: '/safety/hazard',
    title: '隐患排查',
    description: '隐患上报、整改跟踪、闭环验证',
    icon: <WarningOutlined />,
    color: '#dd5b00',
  },
  {
    key: '/safety/accident',
    title: '事故管理',
    description: '事故报告、调查处理、统计分析',
    icon: <AlertOutlined />,
    color: '#e03131',
  },
  {
    key: '/safety/training',
    title: '安全培训',
    description: '培训计划、签到记录、考核管理',
    icon: <BookOutlined />,
    color: '#5645d4',
  },
]

export default function SafetyDashboard() {
  const router = useRouter()
  const [stats, setStats] = useState<DashboardStats>({
    totalChecks: 0,
    pendingChecks: 0,
    openHazards: 0,
    overdueHazards: 0,
    recentAccidents: 0,
    upcomingTrainings: 0,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    try {
      const [checksRes, hazardsRes, accidentsRes, trainingsRes] = await Promise.all([
        getChecks({ page_size: 100 }),
        getHazards({ page_size: 100 }),
        getAccidents({ page_size: 100 }),
        getTrainings({ page_size: 100 }),
      ])

      const checks = checksRes.data || []
      const hazards = hazardsRes.data || []
      const accidents = accidentsRes.data || []
      const trainings = trainingsRes.data || []

      const now = new Date()

      setStats({
        totalChecks: checks.length,
        pendingChecks: checks.filter((c: { status: string }) => c.status === 'submitted').length,
        openHazards: hazards.filter((h: { status: string }) => h.status === 'open').length,
        overdueHazards: hazards.filter((h: { deadline?: string; rectification_status: string }) =>
          h.deadline && new Date(h.deadline) < now && h.rectification_status !== 'verified'
        ).length,
        recentAccidents: accidents.filter((a: { status: string }) => a.status !== 'closed').length,
        upcomingTrainings: trainings.filter((t: { status: string }) => t.status === 'draft' || t.status === 'in_progress').length,
      })
    } catch (error) {
      console.error('Failed to load safety dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Title level={4} className="mb-1">安全管理概览</Title>
        <Text type="secondary">实时监控安全管理状态，保障安全生产</Text>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Spin size="large" />
        </div>
      ) : (
        <>
          {/* Statistics Cards */}
          <Row gutter={16}>
            <Col span={4}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="安全检查"
                  value={stats.totalChecks}
                  suffix={`/${stats.pendingChecks} 待审`}
                  valueStyle={{ color: '#1aae39' }}
                  prefix={<SafetyOutlined />}
                />
              </Card>
            </Col>
            <Col span={5}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="待处理隐患"
                  value={stats.openHazards}
                  suffix={stats.overdueHazards > 0 ? `/${stats.overdueHazards} 逾期` : ''}
                  valueStyle={{ color: stats.overdueHazards > 0 ? '#e03131' : '#dd5b00' }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="未关闭事故"
                  value={stats.recentAccidents}
                  valueStyle={{ color: '#e03131' }}
                  prefix={<AlertOutlined />}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="待办培训"
                  value={stats.upcomingTrainings}
                  valueStyle={{ color: '#5645d4' }}
                  prefix={<BookOutlined />}
                />
              </Card>
            </Col>
          </Row>

          {/* Quick Links */}
          <Row gutter={24}>
            <Col span={24}>
              <Card
                title="功能入口"
                variant="borderless"
                className="shadow-sm"
              >
                <Row gutter={[16, 16]}>
                  {menuItems.map((item) => (
                    <Col span={6} key={item.key}>
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
          </Row>

          {/* Safety Tips */}
          <Row gutter={24}>
            <Col span={24}>
              <Card title="安全提醒" variant="borderless" className="shadow-sm">
                <Row gutter={16}>
                  <Col span={8}>
                    <Space>
                      <CheckCircleOutlined style={{ color: stats.pendingChecks === 0 ? '#1aae39' : '#dd5b00' }} />
                      <Text>
                        {stats.pendingChecks === 0
                          ? '所有检查已审核完成'
                          : `${stats.pendingChecks} 个安全检查待审核`}
                      </Text>
                    </Space>
                  </Col>
                  <Col span={8}>
                    <Space>
                      <ExclamationCircleOutlined style={{ color: stats.overdueHazards > 0 ? '#e03131' : '#1aae39' }} />
                      <Text>
                        {stats.overdueHazards > 0
                          ? `${stats.overdueHazards} 个隐患已逾期未整改`
                          : '暂无逾期隐患'}
                      </Text>
                    </Space>
                  </Col>
                  <Col span={8}>
                    <Space>
                      <BookOutlined style={{ color: stats.upcomingTrainings > 0 ? '#5645d4' : '#1aae39' }} />
                      <Text>
                        {stats.upcomingTrainings > 0
                          ? `${stats.upcomingTrainings} 个培训待完成`
                          : '暂无待办培训'}
                      </Text>
                    </Space>
                  </Col>
                </Row>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  )
}
