'use client'

import { Skeleton, Tooltip } from 'antd'
import {
  ThunderboltOutlined,
  CloudOutlined,
  FireOutlined,
  ExperimentOutlined,
  CompressOutlined,
  BugOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import { EnergyStatistics } from '@/types/energy'

interface StatCardDef {
  key: keyof EnergyStatistics
  title: string
  suffix: string
  icon: React.ReactNode
  color: string
  tint: string
}

const cards: StatCardDef[] = [
  {
    key: 'total_electricity',
    title: '电耗数据',
    suffix: 'kWh',
    icon: <ThunderboltOutlined />,
    color: '#0075de',
    tint: '#dcecfa',
  },
  {
    key: 'total_water',
    title: '水耗数据',
    suffix: 'm³',
    icon: <CloudOutlined />,
    color: '#1aae39',
    tint: '#d9f3e1',
  },
  {
    key: 'total_steam',
    title: '蒸汽数据',
    suffix: 't',
    icon: <FireOutlined />,
    color: '#dd5b00',
    tint: '#ffe8d4',
  },
  {
    key: 'total_cooling',
    title: '冷量数据',
    suffix: 'kW',
    icon: <ExperimentOutlined />,
    color: '#722ed1',
    tint: '#f4ebfa',
  },
  {
    key: 'total_compressed_air',
    title: '压缩空气数据',
    suffix: 'Nm³',
    icon: <CompressOutlined />,
    color: '#2f54eb',
    tint: '#e8ecfc',
  },
  {
    key: 'total_nitrogen',
    title: '氮气数据',
    suffix: 'Nm³',
    icon: <BugOutlined />,
    color: '#fa541c',
    tint: '#ffede8',
  },
  {
    key: 'total_natural_gas',
    title: '天然气数据',
    suffix: 'Nm³',
    icon: <DashboardOutlined />,
    color: '#faad14',
    tint: '#fffbeb',
  },
]

// ── 格式化数值 ──
function formatValue(v: number): string {
  if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M'
  if (Math.abs(v) >= 10_000) return (v / 1_000).toFixed(1) + 'k'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

interface StatsCardsProps {
  statistics: EnergyStatistics
  loading?: boolean
}

export function StatsCards({ statistics, loading = false }: StatsCardsProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 16,
        marginBottom: 20,
      }}
    >
      {cards.map((c) => (
        <div
          key={c.key}
          style={{
            background: '#ffffff',
            borderRadius: 12,
            padding: '20px 24px',
            border: '1px solid #ede9e4',
            boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 16,
          }}
        >
          {/* 图标 — 彩色圆角方块 */}
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 8,
              background: c.tint,
              color: c.color,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
              flexShrink: 0,
            }}
          >
            {c.icon}
          </div>

          {/* 数值 + 标签 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {loading ? (
              <Skeleton.Input active size="small" style={{ width: 100, height: 22 }} />
            ) : (
              <Tooltip
                title={
                  c.key === 'total_water' && statistics[c.key] === 0
                    ? '当前统计值为 0，可能是零值采集数据，建议检查采集日志确认水表读数'
                    : undefined
                }
              >
                <div
                  style={{
                    fontSize: 26,
                    fontWeight: 500,
                    color: '#1a1a1a',
                    lineHeight: 1.2,
                    letterSpacing: '-0.3px',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {formatValue(statistics[c.key])}
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 400,
                      color: '#a4a097',
                      marginLeft: 4,
                    }}
                  >
                    {c.suffix}
                  </span>
                </div>
              </Tooltip>
            )}
            <div
              style={{
                fontSize: 13,
                color: '#787671',
                marginTop: 2,
                lineHeight: 1.4,
              }}
            >
              {c.title}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
