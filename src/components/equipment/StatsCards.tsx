'use client'

import { Card, Col, Row, Statistic } from 'antd'
import { EquipmentStatistics, EquipmentStatus } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

interface StatsCardsProps {
  statistics: EquipmentStatistics
}

const statusCards = [
  { key: '' as const, label: '总数', color: '#1a1a1a', bgColor: undefined },
  { key: '在用' as EquipmentStatus, label: '在用', color: '#1aae39', bgColor: '#e6f7e6' },
  { key: '维修中' as EquipmentStatus, label: '维修中', color: '#dd5b00', bgColor: '#fff7e6' },
  { key: '停用' as EquipmentStatus, label: '停用', color: '#787671', bgColor: '#f0eeec' },
]

export function StatsCards({ statistics }: StatsCardsProps) {
  const { statusFilter, setStatusFilter } = useEquipmentStore()

  const handleClick = (status: EquipmentStatus | '') => {
    setStatusFilter(status)
  }

  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      {statusCards.map(({ key, label, color, bgColor }) => {
        const isActive = statusFilter === key
        const value = key === '' ? statistics.total : (statistics.by_status[key] || 0)

        return (
          <Col span={6} key={key}>
            <Card
              hoverable
              style={{
                cursor: 'pointer',
                background: isActive ? '#ffffff' : bgColor,
                border: isActive ? '2px solid #5645d4' : '2px solid #e5e3df',
                borderRadius: 12,
                transition: 'all 0.2s ease',
              }}
              styles={{
                body: { padding: '16px 20px' },
              }}
              onClick={() => handleClick(key)}
            >
              <Statistic
                title={label}
                value={value}
                styles={{
                  content: { color, fontWeight: 600 },
                  title: { color: '#5d5b54', fontSize: 14 },
                }}
              />
            </Card>
          </Col>
        )
      })}
    </Row>
  )
}
