'use client'

import { useMemo } from 'react'
import { Row, Col, Card } from 'antd'
import {
  FileTextOutlined,
  ClockCircleOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { WorkOrderStatistics, WorkOrderStatus } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

interface StatCardProps {
  title: string
  value: number
  icon: React.ReactNode
  color: string
  bgColor: string
  active?: boolean
  onClick?: () => void
}

function StatCard({ title, value, icon, color, bgColor, active, onClick }: StatCardProps) {
  return (
    <Card
      hoverable
      onClick={onClick}
      style={{
        background: '#ffffff',
        borderRadius: 12,
        border: active ? `2px solid ${color}` : '2px solid #e5e3df',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all 0.2s ease',
      }}
      styles={{ body: { padding: '16px 20px' } }}
    >
      <div className="flex items-center justify-between">
        <div>
          <div style={{ fontSize: 13, color: '#787671', marginBottom: 4 }}>{title}</div>
          <div style={{ fontSize: 28, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.2 }}>
            {value}
          </div>
        </div>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            background: bgColor,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            color,
          }}
        >
          {icon}
        </div>
      </div>
    </Card>
  )
}

const statusCardConfig: {
  key: string
  title: string
  icon: React.ReactNode
  color: string
  bgColor: string
  statusFilter: WorkOrderStatus | ''
}[] = [
  { key: 'total', title: '全部工单', icon: <FileTextOutlined />, color: '#5645d4', bgColor: '#ede9f7', statusFilter: '' },
  { key: 'pending', title: '待处理', icon: <ExclamationCircleOutlined />, color: '#e03131', bgColor: '#fff1f0', statusFilter: '待处理' },
  { key: 'in_progress', title: '维修中', icon: <ToolOutlined />, color: '#dd5b00', bgColor: '#fff7e6', statusFilter: '维修中' },
  { key: 'pending_verify', title: '待验收', icon: <ClockCircleOutlined />, color: '#d4b106', bgColor: '#fffbe6', statusFilter: '待验收' },
  { key: 'completed', title: '已完成', icon: <CheckCircleOutlined />, color: '#1aae39', bgColor: '#e6f7e6', statusFilter: '已完成' },
  { key: 'closed', title: '已关闭', icon: <StopOutlined />, color: '#787671', bgColor: '#f0eeec', statusFilter: '已关闭' },
]

interface WorkOrderStatsCardsProps {
  statistics: WorkOrderStatistics | null
}

export function WorkOrderStatsCards({ statistics }: WorkOrderStatsCardsProps) {
  const { workOrderStatusFilter, setWorkOrderStatusFilter } = useEquipmentStore()

  const statusCounts = useMemo(() => {
    if (!statistics) return {} as Record<string, number>
    return { total: statistics.total, ...statistics.by_status }
  }, [statistics])

  return (
    <Row gutter={[12, 12]}>
      {statusCardConfig.map((config) => (
        <Col key={config.key} flex="1 0 150px">
          <StatCard
            title={config.title}
            value={statusCounts[config.key === 'total' ? 'total' : config.statusFilter] || 0}
            icon={config.icon}
            color={config.color}
            bgColor={config.bgColor}
            active={workOrderStatusFilter === config.statusFilter}
            onClick={() => setWorkOrderStatusFilter(
              workOrderStatusFilter === config.statusFilter ? '' : config.statusFilter,
            )}
          />
        </Col>
      ))}
    </Row>
  )
}
