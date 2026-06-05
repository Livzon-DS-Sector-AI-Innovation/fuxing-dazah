'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Card,
  Row,
  Col,
  Statistic,
  Typography,
  Space,
  Spin,
} from 'antd'
import {
  SafetyOutlined,
  WarningOutlined,
  RobotOutlined,
  FileTextOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
  BookOutlined,
  AlertOutlined,
  SwapOutlined,
  HeartOutlined,
} from '@ant-design/icons'
import { getHazards, getHazardIdentifications, getRegulations } from '@/actions/safety'

const { Title, Text } = Typography

interface DashboardStats {
  openHazards: number
  overdueHazards: number
  totalIdentifications: number
  pendingIdentifications: number
  totalRegulations: number
}

const menuItems = [
  {
    key: '/safety/ai-workflow-config',
    title: 'AI工作流配置',
    description: 'AI工作流管道配置、提示词管理、API接口统一设置',
    icon: <SettingOutlined />,
    color: '#1677ff',
  },
  {
    key: '/safety/ehs-change',
    title: 'EHS变更管理',
    description: '工艺技术、设备设施、管理变更的全生命周期管理（MOC）',
    icon: <SwapOutlined />,
    color: '#13c2c2',
  },
  {
    key: '/safety/occupational-health',
    title: '职业健康管理',
    description: '职业病危害因素监测、职业健康体检、异常处置与合规跟踪',
    icon: <HeartOutlined />,
    color: '#722ed1',
  },
  {
    key: '/safety/hazard',
    title: '隐患排查治理',
    description: '隐患上报、排查整改、闭环验证全流程管理',
    icon: <WarningOutlined />,
    color: '#dd5b00',
  },
  {
    key: '/safety/hazard-identification',
    title: '危险源辨识',
    description: 'AI辅助危险源辨识、LEC风险评价、修订联动',
    icon: <RobotOutlined />,
    color: '#5645d4',
  },
  {
    key: '/safety/regulation',
    title: '安全操规管理',
    description: '安全操作规程文档管理与修订流程',
    icon: <FileTextOutlined />,
    color: '#1aae39',
  },
  {
    key: '/safety/special-ops',
    title: '特殊作业管理',
    description: '八大特殊作业票管理、人员资质证书与有效期跟踪',
    icon: <SafetyCertificateOutlined />,
    color: '#eb2f96',
  },
  {
    key: '/safety/risk-reporting',
    title: '风险作业报备',
    description: '八大特殊作业报备审批、每日风险作业报备管理',
    icon: <AlertOutlined />,
    color: '#e03131',
  },
  {
    key: '/safety/knowledge-base',
    title: '安全知识库',
    description: '法律法规、标准规范、管理制度、事故案例、SDS等知识文档',
    icon: <BookOutlined />,
    color: '#2f54eb',
  },
]

export default function SafetyDashboard() {
  const router = useRouter()
  const [stats, setStats] = useState<DashboardStats>({
    openHazards: 0,
    overdueHazards: 0,
    totalIdentifications: 0,
    pendingIdentifications: 0,
    totalRegulations: 0,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    try {
      const [hazardsRes, identificationsRes, regulationsRes] = await Promise.all([
        getHazards({ page_size: 200 }),
        getHazardIdentifications({ page_size: 200 }),
        getRegulations({ page_size: 200 }),
      ])

      const hazards = hazardsRes.data || []
      const identifications = identificationsRes.data || []
      const regulations = regulationsRes.data || []

      const now = new Date()

      setStats({
        openHazards: hazards.filter((h: { status: string }) => h.status === 'open').length,
        overdueHazards: hazards.filter(
          (h: { deadline?: string; rectification_status: string }) =>
            h.deadline && new Date(h.deadline) < now && h.rectification_status !== 'verified'
        ).length,
        totalIdentifications: identifications.length,
        pendingIdentifications: identifications.filter(
          (i: { overall_status: string }) =>
            i.overall_status === 'draft' || i.overall_status === 'in_progress'
        ).length,
        totalRegulations: regulations.length,
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
        <Title level={4} className="mb-1">安全管理总览</Title>
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
            <Col span={5}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="待处理隐患"
                  value={stats.openHazards}
                  suffix={stats.overdueHazards > 0 ? `${stats.overdueHazards} 逾期` : ''}
                  styles={{ content: { color: stats.overdueHazards > 0 ? '#e03131' : '#dd5b00' } }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
            <Col span={5}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="危险源辨识"
                  value={stats.totalIdentifications}
                  suffix={stats.pendingIdentifications > 0 ? `${stats.pendingIdentifications} 进行中` : ''}
                  styles={{ content: { color: '#5645d4' } }}
                  prefix={<RobotOutlined />}
                />
              </Card>
            </Col>
            <Col span={5}>
              <Card variant="borderless" className="shadow-sm">
                <Statistic
                  title="安全操规"
                  value={stats.totalRegulations}
                  suffix="份"
                  styles={{ content: { color: '#1aae39' } }}
                  prefix={<FileTextOutlined />}
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
                      <ExclamationCircleOutlined
                        style={{ color: stats.overdueHazards > 0 ? '#e03131' : '#1aae39' }}
                      />
                      <Text>
                        {stats.overdueHazards > 0
                          ? `${stats.overdueHazards} 个隐患已逾期未整改，请及时处理`
                          : '暂无逾期隐患'}
                      </Text>
                    </Space>
                  </Col>
                  <Col span={8}>
                    <Space>
                      <RobotOutlined
                        style={{ color: stats.pendingIdentifications > 0 ? '#5645d4' : '#1aae39' }}
                      />
                      <Text>
                        {stats.pendingIdentifications > 0
                          ? `${stats.pendingIdentifications} 个危险源辨识进行中`
                          : '危险源辨识全部完成'}
                      </Text>
                    </Space>
                  </Col>
                  <Col span={8}>
                    <Space>
                      <CheckCircleOutlined style={{ color: '#1aae39' }} />
                      <Text>
                        {stats.totalRegulations > 0
                          ? `共 ${stats.totalRegulations} 份安全操规已录入系统`
                          : '暂无安全操规，请尽快录入'}
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
