'use client'

import { useEffect, useRef, useState } from 'react'
import { ConfigProvider } from 'antd'
import {
  CheckCircleFilled,
  WarningFilled,
  ClockCircleFilled,
  ToolFilled,
  ThunderboltFilled,
  ApartmentOutlined,
  BarChartOutlined,
  PieChartOutlined,
  DashboardOutlined,
  AimOutlined,
  AlertOutlined,
  ExperimentOutlined,
  ScheduleOutlined,
  FileTextOutlined,
  RightOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons'
import type {
  EquipmentStatus,
  WorkOrderStatus,
  WorkOrderPriority,
  WorkOrderType,
  EquipmentStatistics,
  WorkOrderStatistics,
  StockWarning,
  MaintenancePlan,
  CalibrationPlan,
  WorkOrder,
} from '@/types/equipment'
import { antdTheme } from '@/lib/antd-theme'

// ============================================================
// 类型定义
// ============================================================
interface DashboardData {
  equipmentStats: EquipmentStatistics | null
  workOrderStats: WorkOrderStatistics | null
  stockWarnings: StockWarning[]
  overduePlans: MaintenancePlan[]
  calibrationPlans: CalibrationPlan[]
  recentWorkOrders: WorkOrder[]
}

interface StatsDashboardProps {
  initialData: DashboardData
}

// ============================================================
// 工具：数字动画 Hook
// ============================================================
function useCountUp(target: number, duration = 1200) {
  const [value, setValue] = useState(target)
  const raf = useRef<number>(0)
  const startTime = useRef(0)
  const fromValue = useRef(value)
  const prevTarget = useRef(target)

  useEffect(() => {
    if (prevTarget.current === target) return
    prevTarget.current = target
    fromValue.current = value
    startTime.current = 0
    let active = true

    const animate = (timestamp: number) => {
      if (!startTime.current) startTime.current = timestamp
      const elapsed = timestamp - startTime.current
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = Math.round(fromValue.current + (target - fromValue.current) * eased)
      if (active) setValue(current)
      if (progress < 1) {
        raf.current = requestAnimationFrame(animate)
      }
    }

    raf.current = requestAnimationFrame(animate)
    return () => { active = false; cancelAnimationFrame(raf.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, duration])

  return value
}

// ============================================================
// KPI 卡片
// ============================================================
function KpiCard({
  label,
  value,
  suffix,
  icon,
  accentColor,
  trend,
  index,
}: {
  label: string
  value: number | string
  suffix?: string
  icon: React.ReactNode
  accentColor: string
  trend?: { direction: 'up' | 'down'; text: string }
  index: number
}) {
  const numericValue = typeof value === 'number' ? value : 0
  const animatedValue = useCountUp(numericValue)

  return (
    <div
      className="kpi-card"
      style={{
        background: '#ffffff',
        borderRadius: 12,
        padding: '20px 24px',
        border: '1px solid #e5e3df',
        position: 'relative',
        overflow: 'hidden',
        animation: `fadeInUp 0.5s ease both`,
        animationDelay: `${index * 80}ms`,
        transition: 'box-shadow 0.2s ease, transform 0.2s ease',
        cursor: 'default',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = 'rgba(15,15,15,0.08) 0px 4px 12px 0px'
        e.currentTarget.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      {/* 左上角彩色装饰条 */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: 4,
          height: '100%',
          background: accentColor,
          borderRadius: '4px 0 0 4px',
        }}
      />

      {/* 右上角装饰圆 */}
      <div
        style={{
          position: 'absolute',
          top: -12,
          right: -12,
          width: 64,
          height: 64,
          borderRadius: '50%',
          background: `${accentColor}0D`,
          pointerEvents: 'none',
        }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: '#5d5b54',
              marginBottom: 8,
              letterSpacing: '0.01em',
            }}
          >
            {label}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
            <span
              style={{
                fontSize: 36,
                fontWeight: 700,
                color: '#1a1a1a',
                lineHeight: 1,
                letterSpacing: '-0.02em',
                fontFeatureSettings: '"tnum"',
              }}
            >
              {typeof value === 'number' ? animatedValue.toLocaleString() : value}
            </span>
            {suffix && (
              <span style={{ fontSize: 14, fontWeight: 500, color: '#787671', marginLeft: 2 }}>
                {suffix}
              </span>
            )}
          </div>
          {trend && (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                marginTop: 8,
                fontSize: 12,
                fontWeight: 500,
                color: trend.direction === 'up' ? '#1aae39' : '#e03131',
                background: trend.direction === 'up' ? '#e6f7e6' : '#fff1f0',
                borderRadius: 4,
                padding: '2px 8px',
              }}
            >
              {trend.direction === 'up' ? <RiseOutlined /> : <FallOutlined />}
              {trend.text}
            </div>
          )}
        </div>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: `${accentColor}14`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            color: accentColor,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
      </div>
    </div>
  )
}

// ============================================================
// 设备状态分布条
// ============================================================
const statusColorMap: Record<string, string> = {
  '在用': '#1aae39',
  '备用': '#0075de',
  '维修中': '#dd5b00',
  '停用': '#787671',
  '报废': '#c8c4be',
}

function StatusDistribution({ statistics }: { statistics: EquipmentStatistics }) {
  const total = statistics.total || 1
  const entries = Object.entries(statistics.by_status)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])

  if (entries.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#787671', fontSize: 14 }}>
        暂无设备数据
      </div>
    )
  }

  return (
    <div>
      {/* 层叠条 */}
      <div
        style={{
          display: 'flex',
          height: 12,
          borderRadius: 6,
          overflow: 'hidden',
          marginBottom: 20,
          background: '#f0eeec',
        }}
      >
        {entries.map(([status, count]) => (
          <div
            key={status}
            style={{
              width: `${(count / total) * 100}%`,
              background: statusColorMap[status] || '#c8c4be',
              transition: 'width 0.8s cubic-bezier(0.22, 0.61, 0.36, 1)',
              minWidth: count > 0 ? 4 : 0,
            }}
            title={`${status}: ${count}`}
          />
        ))}
      </div>

      {/* 图例列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {entries.map(([status, count], i) => {
          const pct = ((count / total) * 100).toFixed(1)
          return (
            <div
              key={status}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                animation: `fadeInUp 0.4s ease both`,
                animationDelay: `${i * 60}ms`,
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 3,
                  background: statusColorMap[status] || '#c8c4be',
                  flexShrink: 0,
                }}
              />
              <span style={{ flex: 1, fontSize: 14, color: '#1a1a1a', fontWeight: 500 }}>
                {status}
              </span>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a', fontFeatureSettings: '"tnum"' }}>
                {count}
              </span>
              <span style={{ fontSize: 13, color: '#787671', width: 48, textAlign: 'right', fontFeatureSettings: '"tnum"' }}>
                {pct}%
              </span>
              {/* 微型进度条 */}
              <div style={{ width: 80, height: 4, borderRadius: 2, background: '#f0eeec', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${pct}%`,
                    background: statusColorMap[status] || '#c8c4be',
                    borderRadius: 2,
                    transition: 'width 1s ease',
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ============================================================
// 分类分布水平条
// ============================================================
const categoryBarColors = ['#5645d4', '#7b3ff2', '#0075de', '#2a9d99', '#1aae39', '#dd5b00', '#ff64c8', '#f5d75e']

function CategoryDistribution({ statistics }: { statistics: EquipmentStatistics }) {
  const maxVal = Math.max(...Object.values(statistics.by_category), 1)
  const entries = Object.entries(statistics.by_category)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)

  if (entries.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#787671', fontSize: 14 }}>
        暂无分类数据
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {entries.map(([name, count], i) => {
        const pct = (count / maxVal) * 100
        const color = categoryBarColors[i % categoryBarColors.length]
        return (
          <div
            key={name}
            style={{
              animation: `fadeInUp 0.4s ease both`,
              animationDelay: `${i * 60}ms`,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: 5,
                fontSize: 13,
              }}
            >
              <span style={{ color: '#1a1a1a', fontWeight: 500 }}>{name}</span>
              <span style={{ color: '#787671', fontWeight: 500, fontFeatureSettings: '"tnum"' }}>{count}</span>
            </div>
            <div
              style={{
                height: 8,
                borderRadius: 4,
                background: '#f0eeec',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${pct}%`,
                  background: `linear-gradient(90deg, ${color}DD, ${color})`,
                  borderRadius: 4,
                  transition: 'width 1s cubic-bezier(0.22, 0.61, 0.36, 1)',
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// 工单流转概览
// ============================================================
const orderPipelineStages = [
  { status: '待处理', color: '#e03131', bg: '#fff1f0', icon: <AlertOutlined /> },
  { status: '执行中', color: '#dd5b00', bg: '#fff7e6', icon: <ToolFilled /> },
  { status: '待验收', color: '#d4b106', bg: '#fffbe6', icon: <ClockCircleFilled /> },
  { status: '已完成', color: '#1aae39', bg: '#e6f7e6', icon: <CheckCircleFilled /> },
  { status: '已关闭', color: '#787671', bg: '#f0eeec', icon: <CheckCircleFilled /> },
]

const priorityConfig: Record<string, { color: string; bg: string; dot: string; label: string }> = {
  '紧急': { color: '#e03131', bg: '#fff1f0', dot: '#e03131', label: '紧急' },
  '高': { color: '#dd5b00', bg: '#fff7e6', dot: '#dd5b00', label: '高' },
  '中': { color: '#0075de', bg: '#e6f0fa', dot: '#0075de', label: '中' },
  '低': { color: '#787671', bg: '#f0eeec', dot: '#787671', label: '低' },
}

const typeIcons: Record<string, React.ReactNode> = {
  '故障维修': <WarningFilled />,
  '计划维护': <ScheduleOutlined />,
  '校准': <ExperimentOutlined />,
  '异常处理': <ThunderboltFilled />,
  '日常维护': <ToolFilled />,
}

const typeColors: Record<string, string> = {
  '故障维修': '#e03131',
  '计划维护': '#dd5b00',
  '校准': '#7b3ff2',
  '异常处理': '#e03131',
  '日常维护': '#0075de',
}

function WorkOrderPipeline({ statistics }: { statistics: WorkOrderStatistics }) {
  const total = statistics.total || 0

  return (
    <div>
      {/* ===== 横向流转卡片 ===== */}
      <div
        style={{
          display: 'flex',
          alignItems: 'stretch',
          gap: 0,
          marginBottom: 28,
        }}
      >
        {orderPipelineStages.map((stage, idx) => {
          const count = statistics.by_status[stage.status as keyof typeof statistics.by_status] || 0
          const pct = total > 0 ? ((count / total) * 100).toFixed(0) : '0'

          return (
            <div key={stage.status} style={{ display: 'flex', alignItems: 'stretch', flex: 1 }}>
              {/* 卡片 */}
              <div
                style={{
                  flex: 1,
                  background: '#ffffff',
                  borderRadius: 12,
                  border: `1.5px solid ${count > 0 ? stage.color : '#e5e3df'}`,
                  padding: '18px 16px',
                  textAlign: 'center',
                  animation: `fadeInUp 0.5s ease both`,
                  animationDelay: `${idx * 80}ms`,
                  transition: 'border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease',
                  position: 'relative',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = stage.color
                  e.currentTarget.style.boxShadow = `0 2px 12px ${stage.color}18`
                  e.currentTarget.style.transform = 'translateY(-3px)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = count > 0 ? stage.color : '#e5e3df'
                  e.currentTarget.style.boxShadow = 'none'
                  e.currentTarget.style.transform = 'translateY(0)'
                }}
              >
                {/* 顶部彩色圆点 + 百分比 */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, marginBottom: 8 }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: stage.color,
                      display: 'inline-block',
                      flexShrink: 0,
                      animation: count > 0 ? 'pulse 2s ease infinite' : 'none',
                    }}
                  />
                  <span style={{ fontSize: 11, fontWeight: 500, color: '#787671', fontFeatureSettings: '"tnum"' }}>
                    {pct}%
                  </span>
                </div>

                {/* 数字 */}
                <div
                  style={{
                    fontSize: 32,
                    fontWeight: 700,
                    color: count > 0 ? stage.color : '#c8c4be',
                    lineHeight: 1.1,
                    fontFeatureSettings: '"tnum"',
                    marginBottom: 6,
                  }}
                >
                  {count}
                </div>

                {/* 图标 + 标签 */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                  <span style={{ fontSize: 13, color: stage.color, display: 'flex' }}>
                    {stage.icon}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                    {stage.status}
                  </span>
                </div>

                {/* 底部百分比条 */}
                <div
                  style={{
                    height: 3,
                    borderRadius: 2,
                    background: '#f0eeec',
                    marginTop: 12,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${pct}%`,
                      background: stage.color,
                      borderRadius: 2,
                      transition: 'width 0.8s cubic-bezier(0.22, 0.61, 0.36, 1)',
                    }}
                  />
                </div>
              </div>

              {/* 箭头连接 */}
              {idx < orderPipelineStages.length - 1 && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 4px',
                    flexShrink: 0,
                    zIndex: 1,
                  }}
                >
                  <div
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      background: '#f6f5f4',
                      border: '1px solid #e5e3df',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 10,
                      color: '#c8c4be',
                    }}
                  >
                    <RightOutlined />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ===== 底部两列分布 ===== */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
          borderTop: '1px solid #ede9e4',
          paddingTop: 20,
        }}
      >
        {/* 按类型分布 */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#5d5b54', marginBottom: 14, letterSpacing: '0.02em' }}>
            按类型分布
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(statistics.by_type)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count], i) => {
                const maxType = Math.max(...Object.values(statistics.by_type), 1)
                const pct = (count / maxType) * 100
                const accent = typeColors[type] || '#5645d4'
                return (
                  <div
                    key={type}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      animation: `fadeInUp 0.4s ease both`,
                      animationDelay: `${i * 50}ms`,
                    }}
                  >
                    <span style={{ fontSize: 13, color: accent, width: 16, textAlign: 'center', flexShrink: 0 }}>
                      {typeIcons[type] || <FileTextOutlined />}
                    </span>
                    <span style={{ fontSize: 13, color: '#1a1a1a', fontWeight: 500, width: 60, flexShrink: 0 }}>
                      {type}
                    </span>
                    <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#f0eeec', overflow: 'hidden' }}>
                      <div
                        style={{
                          height: '100%',
                          width: `${pct}%`,
                          background: `linear-gradient(90deg, ${accent}CC, ${accent})`,
                          borderRadius: 3,
                          transition: 'width 1s cubic-bezier(0.22, 0.61, 0.36, 1)',
                        }}
                      />
                    </div>
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: '#1a1a1a',
                        width: 32,
                        textAlign: 'right',
                        flexShrink: 0,
                        fontFeatureSettings: '"tnum"',
                      }}
                    >
                      {count}
                    </span>
                  </div>
                )
              })}
          </div>
        </div>

        {/* 按优先级分布 */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#5d5b54', marginBottom: 14, letterSpacing: '0.02em' }}>
            按优先级分布
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 10,
            }}
          >
            {Object.entries(priorityConfig).map(([priority, config], i) => {
              const count = statistics.by_priority[priority as keyof typeof statistics.by_priority] || 0
              const maxPriority = Math.max(...Object.values(statistics.by_priority), 1)
              const pct = ((count / maxPriority) * 100).toFixed(0)
              return (
                <div
                  key={priority}
                  style={{
                    background: '#fafaf9',
                    borderRadius: 10,
                    border: '1px solid #ede9e4',
                    padding: '14px 16px',
                    animation: `fadeInUp 0.4s ease both`,
                    animationDelay: `${i * 60}ms`,
                    transition: 'border-color 0.2s ease',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = config.color }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#ede9e4' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background: config.dot,
                        display: 'inline-block',
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontSize: 12, color: '#5d5b54', fontWeight: 500 }}>{config.label}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                    <span
                      style={{
                        fontSize: 24,
                        fontWeight: 700,
                        color: '#1a1a1a',
                        lineHeight: 1.1,
                        fontFeatureSettings: '"tnum"',
                      }}
                    >
                      {count}
                    </span>
                    <span style={{ fontSize: 11, color: '#a4a097' }}>个</span>
                  </div>
                  {/* 微型进度条 */}
                  <div
                    style={{
                      height: 3,
                      borderRadius: 2,
                      background: '#f0eeec',
                      marginTop: 8,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${pct}%`,
                        background: config.color,
                        borderRadius: 2,
                        transition: 'width 0.8s ease',
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// 预警面板
// ============================================================
function WarningPanels({
  stockWarnings,
  overduePlans,
  calibrationPlans,
}: {
  stockWarnings: StockWarning[]
  overduePlans: MaintenancePlan[]
  calibrationPlans: CalibrationPlan[]
}) {
  const today = new Date()
  const thirtyDaysLater = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000)
  const upcomingCals = calibrationPlans
    .filter(c => c.next_calibration_date && new Date(c.next_calibration_date) <= thirtyDaysLater && new Date(c.next_calibration_date) >= today)
    .slice(0, 5)

  const panels = [
    {
      title: '备件库存预警',
      count: stockWarnings.length,
      icon: <AlertOutlined />,
      accent: '#e03131',
      bg: '#fff1f0',
      border: '#ffa8a8',
      emptyText: '暂无库存预警',
      items: stockWarnings.slice(0, 5).map(w => ({
        key: w.spare_part_id,
        label: w.name,
        sub: `${w.code}`,
        meta: (
          <span style={{ color: '#e03131', fontWeight: 600, fontSize: 13 }}>
            仅剩 {w.current_qty}{' '}
            <span style={{ color: '#787671', fontWeight: 400 }}>/ 最低 {w.min_qty}</span>
          </span>
        ),
      })),
    },
    {
      title: '逾期维护计划',
      count: overduePlans.length,
      icon: <ScheduleOutlined />,
      accent: '#dd5b00',
      bg: '#fff7e6',
      border: '#ffd591',
      emptyText: '暂无逾期计划',
      items: overduePlans.slice(0, 5).map(p => ({
        key: p.id,
        label: p.plan_name || p.equipment_name || '',
        sub: p.equipment_name || p.equipment_no || '',
        meta: (
          <span style={{ color: '#dd5b00', fontWeight: 600, fontSize: 13 }}>
            应于 {p.next_maintenance_date || '—'}
          </span>
        ),
      })),
    },
    {
      title: '校准即将到期',
      count: upcomingCals.length,
      icon: <ExperimentOutlined />,
      accent: '#7b3ff2',
      bg: '#f5f0ff',
      border: '#d6b6f6',
      emptyText: '暂无到期校准',
      items: upcomingCals.map(c => {
        const daysLeft = Math.ceil(
          (new Date(c.next_calibration_date!).getTime() - today.getTime()) / (1000 * 60 * 60 * 24),
        )
        return {
          key: c.id,
          label: c.equipment_name || c.equipment_no || '',
          sub: c.calibration_type,
          meta: (
            <span
              style={{
                color: daysLeft <= 7 ? '#e03131' : '#dd5b00',
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              {daysLeft} 天后到期
            </span>
          ),
        }
      }),
    },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
      {panels.map((panel, pi) => (
        <div
          key={panel.title}
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            borderLeft: `3px solid ${panel.accent}`,
            padding: '20px 20px 16px',
            animation: `fadeInUp 0.5s ease both`,
            animationDelay: `${pi * 100}ms`,
            transition: 'box-shadow 0.2s ease, border-color 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = 'rgba(15,15,15,0.06) 0px 4px 12px 0px'
            e.currentTarget.style.borderColor = panel.border
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = 'none'
            e.currentTarget.style.borderColor = '#e5e3df'
          }}
        >
          {/* 标题行 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: panel.bg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 16,
                color: panel.accent,
                flexShrink: 0,
              }}
            >
              {panel.icon}
            </div>
            <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>{panel.title}</span>
            {panel.count > 0 && (
              <span
                style={{
                  background: panel.accent,
                  color: '#ffffff',
                  fontSize: 12,
                  fontWeight: 700,
                  borderRadius: 9999,
                  padding: '1px 8px',
                  minWidth: 22,
                  textAlign: 'center',
                  fontFeatureSettings: '"tnum"',
                }}
              >
                {panel.count}
              </span>
            )}
          </div>

          {/* 列表 */}
          {panel.items.length === 0 ? (
            <div style={{ padding: '20px 0', textAlign: 'center', color: '#a4a097', fontSize: 13 }}>
              {panel.emptyText}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {panel.items.map((item, ii) => (
                <div
                  key={item.key}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '8px 10px',
                    background: '#fafaf9',
                    borderRadius: 6,
                    border: '1px solid #ede9e4',
                    animation: `fadeInUp 0.3s ease both`,
                    animationDelay: `${ii * 50}ms`,
                    transition: 'border-color 0.15s ease',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = panel.border }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#ede9e4' }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        color: '#1a1a1a',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {item.label}
                    </div>
                    {item.sub && (
                      <div style={{ fontSize: 12, color: '#787671', marginTop: 1 }}>{item.sub}</div>
                    )}
                  </div>
                  <div style={{ flexShrink: 0, marginLeft: 12 }}>{item.meta}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ============================================================
// 近期工单列表
// ============================================================
const workOrderStatusStyle: Record<string, { color: string; bg: string }> = {
  '待处理': { color: '#e03131', bg: '#fff1f0' },
  '执行中': { color: '#dd5b00', bg: '#fff7e6' },
  '待验收': { color: '#d4b106', bg: '#fffbe6' },
  '已完成': { color: '#1aae39', bg: '#e6f7e6' },
  '已关闭': { color: '#787671', bg: '#f0eeec' },
}

function RecentWorkOrders({ orders }: { orders: WorkOrder[] }) {
  if (orders.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#787671', fontSize: 14 }}>
        暂无近期工单
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {orders.map((order, i) => {
        const style = workOrderStatusStyle[order.status] || { color: '#787671', bg: '#f0eeec' }
        return (
          <div
            key={order.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 14px',
              background: '#fafaf9',
              borderRadius: 8,
              border: '1px solid #ede9e4',
              animation: `fadeInUp 0.3s ease both`,
              animationDelay: `${i * 60}ms`,
              transition: 'border-color 0.2s ease',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#c8c4be' }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#ede9e4' }}
          >
            {/* 左侧优先级色条 */}
            <div
              style={{
                width: 3,
                height: 32,
                borderRadius: 2,
                background:
                  order.priority === '紧急' ? '#e03131'
                  : order.priority === '高' ? '#dd5b00'
                  : order.priority === '中' ? '#0075de'
                  : '#c8c4be',
                flexShrink: 0,
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: '#1a1a1a' }}>
                {order.work_order_no}
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: '#787671',
                  marginTop: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {order.equipment_name || order.equipment_no} · {order.order_type}
              </div>
            </div>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: '2px 8px',
                borderRadius: 9999,
                background: style.bg,
                color: style.color,
                whiteSpace: 'nowrap',
              }}
            >
              {order.status}
            </span>
            <span style={{ fontSize: 12, color: '#a4a097', whiteSpace: 'nowrap' }}>
              {order.created_at ? new Date(order.created_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// 主仪表盘组件
// ============================================================
export function StatsDashboard({ initialData }: StatsDashboardProps) {
  const {
    equipmentStats,
    workOrderStats,
    stockWarnings,
    overduePlans,
    calibrationPlans,
    recentWorkOrders,
  } = initialData

  const eq = equipmentStats || { total: 0, by_status: {} as Record<EquipmentStatus, number>, by_category: {} as Record<string, number>, by_location: {} as Record<string, number> }
  const wo = workOrderStats || { total: 0, by_status: {} as Record<WorkOrderStatus, number>, by_type: {} as Record<WorkOrderType, number>, by_priority: {} as Record<WorkOrderPriority, number> }
  const onlineCount = (eq.by_status['在用'] || 0) + (eq.by_status['备用'] || 0)
  const onlineRate = eq.total > 0 ? ((onlineCount / eq.total) * 100).toFixed(1) : '0'
  const pendingOrders = wo.by_status['待处理'] || 0
  const urgentOrders = wo.by_priority['紧急'] || 0

  const quickLinks = [
    { label: '设备台账', href: '/equipment/assets', icon: <ApartmentOutlined />, accent: '#5645d4', bg: '#ede9f8' },
    { label: '维护管理', href: '/equipment/maintenance', icon: <ToolFilled />, accent: '#dd5b00', bg: '#fff7e6' },
    { label: '备件管理', href: '/equipment/spare-parts', icon: <DashboardOutlined />, accent: '#0075de', bg: '#e6f0fa' },
    { label: '巡检管理', href: '/equipment/inspection', icon: <AimOutlined />, accent: '#1aae39', bg: '#e6f7e6' },
  ]

  return (
    <ConfigProvider theme={antdTheme}>
      {/* 全局 keyframes */}
      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes shimmer {
          0%   { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%      { opacity: 0.6; }
        }
        @keyframes dotFloat {
          0%, 100% { transform: translateY(0) scale(1); }
          50%      { transform: translateY(-4px) scale(1.15); }
        }
        .kpi-card:hover .kpi-decor-dot {
          animation: dotFloat 0.6s ease;
        }
        a:hover .quick-link-bg-dot {
          opacity: 0.06 !important;
        }
        a:hover .anticon-right {
          transform: translateX(3px);
          color: #5d5b54 !important;
        }
      `}</style>

      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto'
        }}
      >
        {/* ========== 页面标题 ========== */}
        <div
          style={{
            marginBottom: 28,
            animation: 'fadeInUp 0.5s ease both',
          }}
        >
          <h1
            style={{
              fontSize: 28,
              fontWeight: 600,
              color: '#1a1a1a',
              lineHeight: 1.25,
              margin: 0,
              letterSpacing: '-0.01em',
            }}
          >
            设备管理概览
          </h1>
          <p
            style={{
              fontSize: 14,
              color: '#787671',
              margin: '6px 0 0',
              lineHeight: 1.5,
            }}
          >
            实时数据仪表盘 · 设备部全景视图
          </p>
        </div>

        {/* ========== 快捷入口行 ========== */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 12,
            marginBottom: 28,
          }}
        >
          {quickLinks.map((link, i) => (
            <a
              key={link.href}
              href={link.href}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '14px 20px',
                background: '#ffffff',
                borderRadius: 12,
                border: '1px solid #e5e3df',
                textDecoration: 'none',
                animation: `fadeInUp 0.45s ease both`,
                animationDelay: `${80 + i * 70}ms`,
                transition: 'all 0.25s cubic-bezier(0.22, 0.61, 0.36, 1)',
                position: 'relative',
                overflow: 'hidden',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = link.accent
                e.currentTarget.style.boxShadow = `0 4px 16px ${link.accent}18`
                e.currentTarget.style.transform = 'translateY(-3px)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#e5e3df'
                e.currentTarget.style.boxShadow = 'none'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
            >
              {/* 悬浮时显现的背景圆 */}
              <div
                style={{
                  position: 'absolute',
                  right: -16,
                  top: -16,
                  width: 64,
                  height: 64,
                  borderRadius: '50%',
                  background: link.accent,
                  opacity: 0,
                  transition: 'opacity 0.25s ease',
                }}
                className="quick-link-bg-dot"
              />
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 10,
                  background: link.bg,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 17,
                  color: link.accent,
                  flexShrink: 0,
                  transition: 'transform 0.25s ease, background 0.25s ease',
                }}
              >
                {link.icon}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.3 }}>
                  {link.label}
                </div>
                <div style={{ fontSize: 12, color: '#a4a097', marginTop: 1 }}>
                  进入模块
                </div>
              </div>
              <RightOutlined
                style={{
                  fontSize: 11,
                  color: '#c8c4be',
                  transition: 'transform 0.25s ease, color 0.25s ease',
                  flexShrink: 0,
                }}
              />
            </a>
          ))}
        </div>

        {/* ========== KPI 卡片行 ========== */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 16,
            marginBottom: 28,
          }}
        >
          <KpiCard
            label="设备总数"
            value={eq.total}
            suffix="台"
            icon={<ApartmentOutlined />}
            accentColor="#5645d4"
            trend={{ direction: 'up', text: '设备台账' }}
            index={0}
          />
          <KpiCard
            label="设备在线率"
            value={`${onlineRate}%`}
            icon={<CheckCircleFilled />}
            accentColor="#1aae39"
            trend={{ direction: 'up', text: `在线 ${onlineCount} 台` }}
            index={1}
          />
          <KpiCard
            label="待处理工单"
            value={pendingOrders}
            suffix="个"
            icon={<AlertOutlined />}
            accentColor="#e03131"
            trend={urgentOrders > 0 ? { direction: 'down', text: `紧急 ${urgentOrders} 个` } : undefined}
            index={2}
          />
          <KpiCard
            label="库存预警"
            value={stockWarnings.length}
            suffix="项"
            icon={<WarningFilled />}
            accentColor="#dd5b00"
            trend={stockWarnings.length > 0 ? { direction: 'down', text: '需及时补货' } : undefined}
            index={3}
          />
        </div>

        {/* ========== 第二行：设备全景 + 工单概览 ========== */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 16,
            marginBottom: 28,
          }}
        >
          {/* 设备状态分布 */}
          <div
            style={{
              background: '#ffffff',
              borderRadius: 12,
              border: '1px solid #e5e3df',
              padding: '20px 24px',
              animation: 'fadeInUp 0.5s ease both',
              animationDelay: '320ms',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18 }}>
              <BarChartOutlined style={{ fontSize: 16, color: '#5645d4' }} />
              <h3 style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
                设备状态分布
              </h3>
              <span style={{ fontSize: 12, color: '#a4a097', marginLeft: 'auto' }}>
                共 {eq.total} 台
              </span>
            </div>
            <StatusDistribution statistics={eq} />
          </div>

          {/* 设备分类分布 */}
          <div
            style={{
              background: '#ffffff',
              borderRadius: 12,
              border: '1px solid #e5e3df',
              padding: '20px 24px',
              animation: 'fadeInUp 0.5s ease both',
              animationDelay: '400ms',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18 }}>
              <PieChartOutlined style={{ fontSize: 16, color: '#7b3ff2' }} />
              <h3 style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
                按分类分布
              </h3>
            </div>
            <CategoryDistribution statistics={eq} />
          </div>
        </div>

        {/* ========== 第三行：工单流转 ========== */}
        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            padding: '24px 28px',
            marginBottom: 28,
            animation: 'fadeInUp 0.5s ease both',
            animationDelay: '480ms',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
            <ThunderboltFilled style={{ fontSize: 16, color: '#dd5b00' }} />
            <h3 style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
              工单流转概览
            </h3>
            <span style={{ fontSize: 12, color: '#a4a097', marginLeft: 'auto' }}>
              共 {wo.total} 个工单
            </span>
          </div>
          <WorkOrderPipeline statistics={wo} />
        </div>

        {/* ========== 第四行：预警面板 ========== */}
        <div style={{ marginBottom: 28 }}>
          <WarningPanels
            stockWarnings={stockWarnings}
            overduePlans={overduePlans}
            calibrationPlans={calibrationPlans}
          />
        </div>

        {/* ========== 第五行：近期工单（全宽） ========== */}
        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            border: '1px solid #e5e3df',
            padding: '20px 24px',
            animation: 'fadeInUp 0.5s ease both',
            animationDelay: '560ms',
            marginBottom: 28,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <FileTextOutlined style={{ fontSize: 16, color: '#0075de' }} />
            <h3 style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
              近期工单
            </h3>
          </div>
          <RecentWorkOrders orders={recentWorkOrders} />
        </div>
      </div>
    </ConfigProvider>
  )
}
