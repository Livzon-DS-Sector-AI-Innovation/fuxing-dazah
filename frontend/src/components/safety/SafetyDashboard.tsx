'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Row, Col, Typography, Space, Tag, Drawer, Table } from 'antd'
import {
  WarningOutlined,
  RobotOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  AlertOutlined,
  ClockCircleOutlined,
  EnvironmentOutlined,
  UserOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { SpecialOperationReport, DailyRiskReport, TrainingRecord } from '@/types/safety'
import { T } from './shared-styles'

const { Title, Text } = Typography

// ── Types ──

export interface DashboardData {
  openHazardCount: number
  unfinishedIdentCount: number
  expiringCerts: TrainingRecord[]
  todaySpecialOps: SpecialOperationReport[]
  todayDailyRisks: DailyRiskReport[]
}

interface TodayRiskRow {
  key: string
  source: 'special_op' | 'daily_risk'
  sourceLabel: string
  operationType: string
  operationDescription: string
  riskLevel: string
  location: string
  department: string
  responsiblePerson: string
  timeRange: string
  status: string
}

// ── Operation type labels ──

const OP_TYPE_LABELS: Record<string, string> = {
  hot_work: '动火作业',
  confined_space: '受限空间',
  height_work: '高处作业',
  temporary_electricity: '临时用电',
  blind_plate: '盲板抽堵',
  excavation: '动土作业',
  lifting: '起重吊装',
  pipeline: '管线打开',
}

function opTypeLabel(type: string): string {
  return OP_TYPE_LABELS[type] || type
}

// ── Risk level config ──

function riskLevelConfig(level?: string): { color: string; bg: string; label: string } {
  const l = level ?? ''
  if (l.includes('一') || l.includes('重大') || l.includes('1')) {
    return { color: '#DC2626', bg: '#fef2f2', label: l || '一级' }
  }
  if (l.includes('二') || l.includes('较大') || l.includes('2')) {
    return { color: '#F97316', bg: '#fff7ed', label: l || '二级' }
  }
  if (l.includes('三') || l.includes('一般') || l.includes('3')) {
    return { color: '#CA8A04', bg: '#fefce8', label: l || '三级' }
  }
  if (l.includes('四') || l.includes('低') || l.includes('4')) {
    return { color: '#16A34A', bg: '#f0fdf4', label: l || '四级' }
  }
  return { color: T.steel, bg: T.surface, label: l || '-' }
}

// ── Certificate expiry status ──

function certExpiryTag(expiry?: string): { color: string; bg: string; text: string } {
  if (!expiry) return { color: T.steel, bg: T.surface, text: '未知' }
  const days = Math.ceil((new Date(expiry).getTime() - Date.now()) / 86400000)
  if (days < 0) return { color: '#DC2626', bg: '#fef2f2', text: '已过期' }
  if (days <= 7) return { color: '#F97316', bg: '#fff7ed', text: `${days}天后到期` }
  return { color: '#CA8A04', bg: '#fefce8', text: `${days}天后到期` }
}

// ═══════════════════════════════════════════════════════════════
// KPI Card (clickable)
// ═══════════════════════════════════════════════════════════════

function KpiCard({
  label,
  value,
  suffix,
  color,
  bg,
  icon,
  onClick,
}: {
  label: string
  value: number
  suffix?: string
  color: string
  bg: string
  icon: React.ReactNode
  onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      className="rounded-xl p-5 border transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md group"
      style={{
        backgroundColor: T.canvas,
        borderColor: T.hairline,
        borderRadius: 12,
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      <div className="flex items-start justify-between mb-3">
        <Text
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: T.slate, fontSize: 11, letterSpacing: '0.5px' }}
        >
          {label}
        </Text>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center text-base"
          style={{ backgroundColor: bg, color }}
        >
          {icon}
        </div>
      </div>
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-1">
          <span
            className="text-3xl font-semibold tracking-tight"
            style={{ color, fontFamily: "'Notion Sans', Inter, system-ui, sans-serif" }}
          >
            {value}
          </span>
          {suffix && (
            <span className="text-sm" style={{ color: T.steel }}>
              {suffix}
            </span>
          )}
        </div>
        {onClick && (
          <ArrowRightOutlined
            className="opacity-0 group-hover:opacity-100 transition-opacity duration-200"
            style={{ color: T.muted, fontSize: 12 }}
          />
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Main Dashboard
// ═══════════════════════════════════════════════════════════════

export default function SafetyDashboard({ data }: { data: DashboardData }) {
  const router = useRouter()
  const [certDrawerOpen, setCertDrawerOpen] = useState(false)

  const hasAlerts = data.expiringCerts.length > 0

  // ── Certificate table columns ──

  const certColumns: ColumnsType<TrainingRecord> = [
    {
      title: '姓名',
      dataIndex: 'employee_name',
      key: 'name',
      width: 100,
      render: (v) => <Text style={{ color: T.charcoal }}>{v || '-'}</Text>,
    },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'dept',
      width: 100,
      render: (v) => <Text style={{ color: T.steel }}>{v || '-'}</Text>,
    },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 100,
      render: (v) => <Text style={{ color: T.steel }}>{v || '-'}</Text>,
    },
    {
      title: '证书编号',
      dataIndex: 'certificate_no',
      key: 'cert_no',
      width: 150,
      render: (v) => <Text style={{ color: T.charcoal, fontFamily: 'monospace' }}>{v || '-'}</Text>,
    },
    {
      title: '到期时间',
      dataIndex: 'certificate_expiry',
      key: 'expiry',
      width: 120,
      render: (v: string) => (
        <Text style={{ color: T.charcoal, fontWeight: 500 }}>
          {v ? new Date(v).toLocaleDateString('zh-CN') : '-'}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'certificate_expiry',
      key: 'status',
      width: 110,
      render: (v: string) => {
        const tag = certExpiryTag(v)
        return (
          <Tag
            style={{
              color: tag.color,
              backgroundColor: tag.bg,
              border: 'none',
              borderRadius: 6,
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {tag.text}
          </Tag>
        )
      },
    },
  ]

  // ── Today risk rows ──

  const todayRisks: TodayRiskRow[] = [
    ...data.todaySpecialOps.map((r) => {
      const rl = riskLevelConfig(r.risk_level)
      return {
        key: `so-${r.id}`,
        source: 'special_op' as const,
        sourceLabel: '特殊作业',
        operationType: opTypeLabel(r.operation_type),
        operationDescription: r.work_description || '-',
        riskLevel: rl.label,
        location: r.location || '-',
        department: r.department || '-',
        responsiblePerson: r.work_leader_name || r.guardian_name || '-',
        timeRange: [r.planned_start_time, r.planned_end_time]
          .filter(Boolean)
          .map((t) => (t ? new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''))
          .join(' – ') || '-',
        status: r.status,
      }
    }),
    ...data.todayDailyRisks.map((r) => {
      const rl = riskLevelConfig(r.risk_level)
      return {
        key: `dr-${r.id}`,
        source: 'daily_risk' as const,
        sourceLabel: '每日报备',
        operationType: r.operation_description.slice(0, 12) + (r.operation_description.length > 12 ? '…' : ''),
        operationDescription: r.operation_description,
        riskLevel: rl.label,
        location: r.location || '-',
        department: r.department || '-',
        responsiblePerson: r.responsible_person || r.applicant_name || '-',
        timeRange: [r.planned_start_time, r.planned_end_time]
          .filter(Boolean)
          .map((t) => (t ? new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''))
          .join(' – ') || '-',
        status: r.status,
      }
    }),
  ]

  const totalTodayRisks = todayRisks.length

  // ── Render ──

  return (
    <div className="space-y-6 pb-8">
      {/* ── Header ── */}
      <div>
        <Title level={4} className="!mb-1" style={{ fontFamily: "'Notion Sans', Inter, system-ui, sans-serif" }}>
          安全管理总览
        </Title>
        <Text style={{ color: T.slate, fontSize: 14 }}>
          实时监控安全管理状态 · 保障安全生产
        </Text>
      </div>

      {/* ── Alert Banner ── */}
      {hasAlerts && (
        <div
          onClick={() => setCertDrawerOpen(true)}
          className="rounded-xl p-4 flex items-center gap-3 cursor-pointer transition-all duration-200 hover:-translate-y-0.5"
          style={{ backgroundColor: T.yellowBold, borderRadius: 12 }}
        >
          <ClockCircleOutlined style={{ color: T.warning, fontSize: 18 }} />
          <Text strong style={{ color: T.charcoal, fontSize: 14 }}>
            {data.expiringCerts.length} 个培训证书即将到期，点击查看详情
          </Text>
          <ArrowRightOutlined style={{ color: T.warning, marginLeft: 'auto' }} />
        </div>
      )}

      {/* ── KPI Cards Row ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <KpiCard
            label="未关闭隐患"
            value={data.openHazardCount}
            suffix="条"
            color={T.warning}
            bg={T.peach}
            icon={<WarningOutlined />}
            onClick={() => router.push('/safety/hazard')}
          />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard
            label="即将到期证书"
            value={data.expiringCerts.length}
            suffix="张"
            color={data.expiringCerts.length > 0 ? T.error : T.success}
            bg={data.expiringCerts.length > 0 ? T.rose : T.mint}
            icon={<ClockCircleOutlined />}
            onClick={() => setCertDrawerOpen(true)}
          />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard
            label="危险源辨识未完成"
            value={data.unfinishedIdentCount}
            suffix="条"
            color={data.unfinishedIdentCount > 0 ? T.primary : T.success}
            bg={T.lavender}
            icon={<RobotOutlined />}
            onClick={() => router.push('/safety/hazard-identification')}
          />
        </Col>
      </Row>

      {/* ── 今日关键风险作业 ── */}
      <Card
        variant="borderless"
        className="!shadow-sm"
        style={{ borderRadius: 12, border: `1px solid ${T.hairline}` }}
        title={
          <Space>
            <AlertOutlined style={{ color: T.error }} />
            <Text strong style={{ fontSize: 15, color: T.charcoal }}>
              今日关键风险作业
            </Text>
            {totalTodayRisks > 0 && (
              <span
                className="text-xs font-semibold px-2 py-0.5 rounded"
                style={{ backgroundColor: T.rose, color: T.error, borderRadius: 6 }}
              >
                {totalTodayRisks} 项
              </span>
            )}
          </Space>
        }
      >
        {totalTodayRisks === 0 ? (
          <div className="text-center py-8">
            <CheckCircleOutlined style={{ fontSize: 32, color: T.muted }} />
            <Text className="block mt-2" style={{ color: T.muted }}>
              今日暂无风险作业
            </Text>
          </div>
        ) : (
          <>
            {/* Table header — desktop only */}
            <div
              className="hidden md:grid gap-3 px-4 py-2.5 rounded-lg mb-1"
              style={{
                gridTemplateColumns: '1fr 80px 120px 100px 140px 100px 100px',
                backgroundColor: T.surface,
                borderRadius: 8,
              }}
            >
              {['作业内容', '风险等级', '作业地点', '部门', '负责人/监护人', '时段', '来源'].map((h) => (
                <Text key={h} className="text-xs font-semibold" style={{ color: T.slate, fontSize: 11 }}>
                  {h}
                </Text>
              ))}
            </div>

            <div className="space-y-1">
              {todayRisks.map((row) => {
                const rl = riskLevelConfig(row.riskLevel)
                const isSpecialOp = row.source === 'special_op'
                return (
                  <div
                    key={row.key}
                    className="grid gap-3 px-4 py-3 rounded-lg cursor-pointer transition-colors hover:bg-[var(--color-surface)]"
                    style={{
                      borderRadius: 8,
                      gridTemplateColumns: '1fr 80px 120px 100px 140px 100px 100px',
                    }}
                    onClick={() => router.push(isSpecialOp ? '/safety/special-ops' : '/safety/risk-reporting')}
                  >
                    {/* 作业内容 */}
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: rl.color }} />
                      <Text className="text-sm truncate" style={{ color: T.charcoal }} title={row.operationDescription}>
                        {row.operationType}
                      </Text>
                    </div>

                    {/* 风险等级 */}
                    <div className="flex items-center">
                      <Tag
                        style={{
                          color: rl.color, backgroundColor: rl.bg, border: 'none',
                          borderRadius: 6, fontSize: 11, fontWeight: 600, margin: 0,
                        }}
                      >
                        {rl.label}
                      </Tag>
                    </div>

                    {/* 作业地点 */}
                    <div className="flex items-center gap-1 min-w-0">
                      <EnvironmentOutlined style={{ color: T.muted, fontSize: 11, flexShrink: 0 }} />
                      <Text className="text-xs truncate" style={{ color: T.steel }} title={row.location}>{row.location}</Text>
                    </div>

                    {/* 部门 */}
                    <div className="flex items-center gap-1 min-w-0">
                      <TeamOutlined style={{ color: T.muted, fontSize: 11, flexShrink: 0 }} />
                      <Text className="text-xs truncate" style={{ color: T.steel }} title={row.department}>{row.department}</Text>
                    </div>

                    {/* 负责人 */}
                    <div className="flex items-center gap-1 min-w-0">
                      <UserOutlined style={{ color: T.muted, fontSize: 11, flexShrink: 0 }} />
                      <Text className="text-xs truncate" style={{ color: T.steel }} title={row.responsiblePerson}>{row.responsiblePerson}</Text>
                    </div>

                    {/* 时段 */}
                    <div className="flex items-center">
                      <Text className="text-xs" style={{ color: T.steel }}>{row.timeRange}</Text>
                    </div>

                    {/* 来源 */}
                    <div className="flex items-center">
                      <Tag
                        style={{
                          color: isSpecialOp ? '#1677ff' : '#722ed1',
                          backgroundColor: isSpecialOp ? T.sky : T.lavender,
                          border: 'none', borderRadius: 6, fontSize: 11, fontWeight: 600, margin: 0,
                        }}
                      >
                        {row.sourceLabel}
                      </Tag>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </Card>

      {/* ── Certificate Detail Drawer ── */}
      <Drawer
        title={
          <Space>
            <ClockCircleOutlined style={{ color: T.warning }} />
            <span>即将到期证书</span>
            <Tag
              style={{
                color: T.warning, backgroundColor: T.peach, border: 'none',
                borderRadius: 6, fontSize: 12, fontWeight: 600,
              }}
            >
              {data.expiringCerts.length} 张
            </Tag>
          </Space>
        }
        placement="right"
        size="large"
        open={certDrawerOpen}
        onClose={() => setCertDrawerOpen(false)}
        styles={{ body: { padding: '12px 24px' } }}
      >
        {data.expiringCerts.length === 0 ? (
          <div className="text-center py-12">
            <CheckCircleOutlined style={{ fontSize: 40, color: T.muted }} />
            <Text className="block mt-3" style={{ color: T.muted }}>
              暂无即将到期的证书
            </Text>
          </div>
        ) : (
          <Table<TrainingRecord>
            columns={certColumns}
            dataSource={data.expiringCerts}
            rowKey="id"
            size="middle"
            pagination={false}
            style={{ borderRadius: 8 }}
          />
        )}
      </Drawer>
    </div>
  )
}
