'use client'

import { Skeleton } from 'antd'
import {
  FileTextOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  PlusCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'

interface StatsData {
  total: number
  withCards: number
  injections30d: number
  new30d: number
}

interface StatPill {
  key: string
  label: string
  value: number | string
  suffix?: string
  dotColor: string
  icon: React.ReactNode
  valueColor?: string
}

interface Props {
  stats: StatsData
  loading?: boolean
  onCardFilter?: (filter: string | undefined) => void
  activeCardFilter?: string | undefined
}

export default function DocumentStatsBar({
  stats,
  loading,
  onCardFilter,
  activeCardFilter,
}: Props) {
  const pills: StatPill[] = [
    {
      key: 'total',
      label: '文档总数',
      value: stats.total,
      suffix: '份',
      dotColor: '#0075de',
      icon: <FileTextOutlined style={{ fontSize: 13 }} />,
    },
    {
      key: 'withCards',
      label: '知识卡片',
      value: stats.withCards,
      suffix: `/ ${stats.total}`,
      dotColor: stats.total > 0 && stats.withCards < stats.total ? '#dd5b00' : '#1aae39',
      icon: <RobotOutlined style={{ fontSize: 13 }} />,
      valueColor:
        stats.total > 0 && stats.withCards < stats.total ? '#dd5b00' : '#1aae39',
    },
    {
      key: 'injections30d',
      label: '近30天注入',
      value: stats.injections30d,
      suffix: '次',
      dotColor: '#7b3ff2',
      icon: <ThunderboltOutlined style={{ fontSize: 13 }} />,
    },
    {
      key: 'new30d',
      label: '近30天新增',
      value: stats.new30d,
      suffix: '份',
      dotColor: '#2a9d99',
      icon: <PlusCircleOutlined style={{ fontSize: 13 }} />,
    },
    {
      key: 'sync',
      label: '同步状态',
      value: '正常',
      dotColor: '#1aae39',
      icon: <SyncOutlined style={{ fontSize: 13 }} />,
      valueColor: '#1aae39',
    },
  ]

  if (loading) {
    return (
      <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        {pills.map((p) => (
          <Skeleton.Button key={p.key} active size="small" style={{ width: 120, height: 28 }} />
        ))}
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 20,
      }}
    >
      {pills.map((pill) => {
        const isActive =
          pill.key === 'withCards' && activeCardFilter !== undefined
        const isClickable = pill.key === 'withCards' && onCardFilter

        return (
          <button
            key={pill.key}
            type="button"
            onClick={() => {
              if (!isClickable || !onCardFilter) return
              // Cycle: none → has_card → no_card → none
              if (activeCardFilter === undefined) {
                onCardFilter('has_card')
              } else if (activeCardFilter === 'has_card') {
                onCardFilter('no_card')
              } else {
                onCardFilter(undefined)
              }
            }}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              cursor: isClickable ? 'pointer' : 'default',
              background: isActive ? '#f0eeec' : 'transparent',
              border: isActive ? '1px solid #c8c4be' : '1px solid transparent',
              borderRadius: 20,
              padding: '4px 12px',
              fontSize: 13,
              fontWeight: isActive ? 600 : 400,
              color: isActive ? '#1a1a1a' : '#5d5b54',
              transition: 'all 0.15s ease',
              lineHeight: '20px',
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: pill.dotColor,
                flexShrink: 0,
              }}
            />
            <span style={{ color: '#787671' }}>{pill.icon}</span>
            <span>{pill.label}</span>
            <span
              style={{
                fontWeight: 600,
                color: pill.valueColor || '#1a1a1a',
                marginLeft: 2,
              }}
            >
              {pill.value}
              {pill.suffix && (
                <span style={{ fontWeight: 400, color: '#a4a097', marginLeft: 1 }}>
                  {pill.suffix}
                </span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}
