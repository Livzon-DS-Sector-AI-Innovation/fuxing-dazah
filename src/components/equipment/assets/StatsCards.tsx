'use client'

import { Card, Col, Row, Statistic } from 'antd'
import { EquipmentStatistics, EquipmentStatus } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

interface StatsCardsProps {
  statistics: EquipmentStatistics
  compact?: boolean
}

const statusCards = [
  { key: '' as const, label: '总数', color: '#1a1a1a', dotColor: '#787671' },
  { key: '在用' as EquipmentStatus, label: '在用', color: '#1aae39', dotColor: '#1aae39' },
  { key: '维修中' as EquipmentStatus, label: '维修中', color: '#dd5b00', dotColor: '#dd5b00' },
  { key: '停用' as EquipmentStatus, label: '停用', color: '#787671', dotColor: '#787671' },
]

export function StatsCards({ statistics, compact = false }: StatsCardsProps) {
  const { statusFilter, setStatusFilter } = useEquipmentStore()

  const handleClick = (status: EquipmentStatus | '') => {
    setStatusFilter(status)
  }

  if (compact) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        {statusCards.map(({ key, label, color, dotColor }) => {
          const isActive = statusFilter === key
          const value = key === '' ? statistics.total : (statistics.by_status[key] || 0)

          return (
            <button
              key={key}
              type="button"
              onClick={() => handleClick(key)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                cursor: 'pointer',
                background: isActive ? '#f0eeec' : 'transparent',
                border: isActive ? '1px solid #c8c4be' : '1px solid transparent',
                borderRadius: 20,
                padding: '4px 12px',
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? '#1a1a1a' : '#5d5b54',
                transition: 'all 0.15s ease',
                fontFamily: 'inherit',
                lineHeight: '20px',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: dotColor,
                  flexShrink: 0,
                }}
              />
              {label}
              <span style={{ fontWeight: 600, color, marginLeft: 2 }}>
                {value}
              </span>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      {statusCards.map(({ key, label, color }) => {
        const isActive = statusFilter === key
        const value = key === '' ? statistics.total : (statistics.by_status[key] || 0)

        return (
          <Col span={6} key={key}>
            <Card
              hoverable
              style={{
                cursor: 'pointer',
                background: isActive ? '#ffffff' : '#fafaf9',
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
