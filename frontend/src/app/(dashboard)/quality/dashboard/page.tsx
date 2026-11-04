'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Card, Row, Col, Statistic, Listy, Tag, Button, App, Space, Progress, theme } from 'antd'
import {
  CalendarOutlined, SearchOutlined, LoadingOutlined, CheckCircleOutlined, SunOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import { TASK_STATUS_META } from '@/types/quality'
import type { TestTaskStatus, QualityDashboard, DailyReportItem, QualityAlerts } from '@/types/quality'
import { fetchQualityDashboard, fetchDailyReports, fetchReportRecords, fetchDashboardTrend, fetchDashboardAlerts } from '@/actions/quality'

const { Title, Paragraph, Text } = Typography

const ENV_TYPE_LABELS: Record<string, string> = {
  settle: '沉降菌', float: '浮游菌', particle: '悬浮粒子', temp_humidity: '温湿度', pressure: '压差',
}
const ENV_FREQ_LABELS: Record<string, string> = { weekly: '每周', monthly: '每月', per_batch: '每批' }
const LAB_TYPE_LABELS: Record<string, string> = {
  reagent: '试剂', reference_standard: '对照品', titrant: '滴定液', instrument: '仪器校验',
}

/** 提醒中心单块：有内容列明细，无内容显示正常标记。 */
function AlertBlock({ label, items, danger, empty }: { label: string; items: string[]; danger?: boolean; empty: string }) {
  const { token } = theme.useToken()
  if (!items.length) {
    return (
      <div style={{ paddingBlock: 2 }}>
        <Text type="secondary">✓ {label}：{empty}</Text>
      </div>
    )
  }
  return (
    <div style={{ paddingBlock: 2 }}>
      <Text strong style={{ color: danger ? token.colorError : token.colorWarning }}>{label}（{items.length}）</Text>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
        {items.map((t, i) => (
          <li key={i}><Text style={{ fontSize: 13 }}>{t}</Text></li>
        ))}
      </ul>
    </div>
  )
}

type DashRow = QualityDashboard['today'][number]

function TaskItem({ t }: { t: DashRow }) {
  const router = useRouter()
  const { token } = theme.useToken()
  const pct = t.total ? Math.round((t.filled / t.total) * 100) : 0
  return (
    <div style={{ cursor: 'pointer', paddingBlock: 6 }}
      onClick={() => router.push(`/quality/task/${t.task_id}`)}>
      <div style={{ width: '100%' }}>
        <Space wrap size={6}>
          {t.status === 'completed' && <CheckCircleOutlined style={{ color: token.colorSuccess }} />}
          <Text strong>{t.product_name}</Text>
          <Text type="secondary">批号 {t.batch_number}</Text>
          {t.status === 'in_progress' && t.report_date && t.report_date > dayjs().format('YYYY-MM-DD') ? (
            <Tag color="cyan">待分配</Tag>
          ) : (
            <Tag color={TASK_STATUS_META[t.status as TestTaskStatus]?.color}>{TASK_STATUS_META[t.status as TestTaskStatus]?.label ?? t.status}</Tag>
          )}
          {t.report_date && <Text type="secondary">出报 {t.report_date}</Text>}
        </Space>
        <Progress percent={pct} size="small" format={() => `${t.filled}/${t.total}`}
          style={{ marginTop: 2, marginBottom: 0 }} />
      </div>
    </div>
  )
}

export default function QualityDashboardPage() {
  const router = useRouter()
  const { token } = theme.useToken()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<QualityDashboard | null>(null)
  const [dailyReports, setDailyReports] = useState<DailyReportItem[]>([])
  const [pendingAuditCount, setPendingAuditCount] = useState(0)
  const [trend, setTrend] = useState<{ date: string; reports: number; completed_tasks: number }[]>([])
  const [alerts, setAlerts] = useState<QualityAlerts | null>(null)

  const today = dayjs().format('YYYY-MM-DD')
  const tomorrow = dayjs().add(1, 'day').format('YYYY-MM-DD')

  const load = useCallback(async (silent = false) => {
    try {
      const [res, reports, pendingAudit, trendRes, alertsRes] = await Promise.all([
        fetchQualityDashboard(),
        fetchDailyReports(),
        fetchReportRecords(undefined, undefined, 1, 'pending').catch(() => null),
        fetchDashboardTrend(7).catch(() => null),
        fetchDashboardAlerts().catch(() => null),
      ])
      setData(res.data)
      setDailyReports(reports.data || [])
      setPendingAuditCount(pendingAudit?.meta.total ?? 0)
      setTrend(trendRes?.data ?? [])
      setAlerts(alertsRes?.data ?? null)
    } catch (err: unknown) {
      // 自动刷新静默失败（此前后端异常时每 30 秒弹一条错误轰炸）
      if (!silent) message.error((err instanceof Error ? err.message : String(err)) || '加载总览失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  // 挂载即拉一次（包在 async 内：effect 同步段只发起请求，不直接同步 setState）
  useEffect(() => { (async () => { await load() })() }, [load])

  // 30 秒自动刷新（页面可见时，静默）
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) load(true)
    }, 30000)
    return () => clearInterval(timer)
  }, [load])

  return (
    <div className="space-y-4">
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>质量总览</Title>
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          今日出报、待复核、在途批次一屏总览；点条目直达任务详情，页面每 30 秒自动刷新。
        </Paragraph>
      </div>

      <Row gutter={16}>
        <Col xs={12} sm={12} md={6}>
          <Card size="small" hoverable loading={loading}
            onClick={() => router.push('/quality/report?audit_status=pending')}>
            <Statistic title="待初审报告单" value={pendingAuditCount}
              valueStyle={{ color: pendingAuditCount > 0 ? token.colorWarning : undefined }}
              suffix="份" />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card size="small" hoverable loading={loading}
            onClick={() => router.push(`/quality/task?report_date=${today}`)}>
            <Statistic title="今日出报" value={data?.today.length ?? 0} prefix={<CalendarOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card size="small" hoverable loading={loading}
            onClick={() => router.push('/quality/task?status=pending_review')}>
            <Statistic title="待复核" value={data?.pending_review_count ?? 0}
              prefix={<SearchOutlined />}
              valueStyle={{ color: (data?.pending_review_count ?? 0) > 0 ? token.colorWarning : undefined }} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card size="small" hoverable loading={loading}
            onClick={() => router.push('/quality/task?status=in_progress')}>
            <Statistic title="在途（填报中）" value={data?.in_progress_count ?? 0} prefix={<LoadingOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card size="small" hoverable loading={loading}
            onClick={() => router.push(`/quality/task?report_date=${tomorrow}`)}>
            <Statistic title="明日出报" value={data?.tomorrow_count ?? 0} prefix={<SunOutlined />} />
          </Card>
        </Col>
      </Row>

      {trend.length > 0 && (
        <Card size="small" title="近 7 天趋势（出报单 / 完成任务）">
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', height: 90 }}>
            {trend.map((t) => {
              const max = Math.max(...trend.map((x) => Math.max(x.reports, x.completed_tasks)), 1)
              return (
                <div key={t.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 60 }}>
                    <div title={`出报单 ${t.reports}`} style={{ width: 10, height: `${(t.reports / max) * 56 + 2}px`, background: token.colorPrimary, borderRadius: 2 }} />
                    <div title={`完成任务 ${t.completed_tasks}`} style={{ width: 10, height: `${(t.completed_tasks / max) * 56 + 2}px`, background: token.colorPrimaryBg, borderRadius: 2 }} />
                  </div>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>{t.date.slice(5)}</Typography.Text>
                </div>
              )
            })}
          </div>
          <Space size={16} style={{ marginTop: 4 }}>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}><span style={{ color: token.colorPrimary }}>■</span> 出报单</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}><span style={{ color: token.colorPrimaryBg }}>■</span> 完成任务</Typography.Text>
          </Space>
        </Card>
      )}

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card size="small" title="今日出报任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部</Button>}>
            {data?.today?.length
              ? <Listy items={data.today} rowKey={(t) => t.task_id} itemRender={(t) => <TaskItem t={t} />} />
              : <Text type="secondary">今日无出报任务</Text>}
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="待复核（需两名复核人通过）"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task?status=pending_review')}>全部</Button>}>
            {data?.pending_review?.length
              ? <Listy items={data.pending_review} rowKey={(t) => t.task_id} itemRender={(t) => <TaskItem t={t} />} />
              : <Text type="secondary">暂无待复核任务</Text>}
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="最近完成任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部</Button>}>
            {data?.recent_completed?.length
              ? <Listy items={data.recent_completed} rowKey={(t) => t.task_id} itemRender={(t) => <TaskItem t={t} />} />
              : <Text type="secondary">暂无完成任务</Text>}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="今日报告单（流水号+产品+批号）"
        extra={<Button size="small" type="link" onClick={() => router.push('/quality/report')}>报告单页</Button>}>
        {dailyReports.length
          ? (
              <Listy
                items={dailyReports}
                rowKey={(r) => `${r.serial_no}-${r.batch_number}`}
                itemRender={(r) => (
                  <Space wrap size={8} style={{ paddingBlock: 4 }}>
                    <Text strong>{r.serial_no}</Text>
                    <Text>{r.product_name}</Text>
                    <Text type="secondary">批号 {r.batch_number}</Text>
                    <Text type="secondary">{r.created_at}</Text>
                  </Space>
                )}
              />
            )
          : <Text type="secondary">今日暂无生成报告单</Text>}
      </Card>

      <Card size="small" title={<Space><WarningOutlined style={{ color: token.colorWarning }} />提醒中心</Space>}
        extra={<Space>
          <Button size="small" type="link" onClick={() => router.push('/quality/env')}>环境监测</Button>
          <Button size="small" type="link" onClick={() => router.push('/quality/retained')}>留样台账</Button>
        </Space>}>
        {alerts ? (
          <Space direction="vertical" style={{ width: '100%' }} size={2}>
            <AlertBlock
              label="环境超行动限未处理" danger
              empty="无未处理超限"
              items={alerts.env_action_open.map((r) =>
                `${r.room} ${r.point_no} ${r.record_date} 结果 ${r.result_value}（行动限 ${r.action_limit}）——请标记处理`)}
            />
            <AlertBlock
              label="环境监测欠账（应测未测）"
              empty="周/月频次点位均已检测"
              items={alerts.env_missed.map((m) =>
                `${m.room} ${m.point_no}（${ENV_TYPE_LABELS[m.monitor_type] ?? m.monitor_type}｜${ENV_FREQ_LABELS[m.frequency] ?? m.frequency}）${m.last_date ? `上次检测 ${m.last_date}` : '尚无检测记录'}`)}
            />
            <AlertBlock
              label="留样销毁到期"
              empty="无到期留样"
              items={alerts.retained.map((r) =>
                `${r.sample_name} 批号 ${r.batch_no}：到期 ${r.destroy_due_date}${r.expired ? '（已过期未销毁）' : '（30 天内）'}${r.location ? `｜位置 ${r.location}` : ''}`)}
            />
            <AlertBlock
              label="试剂/仪器效期"
              empty="无临期或过期"
              items={alerts.lab.map((a) =>
                `${LAB_TYPE_LABELS[a.item_type] ?? a.item_type} ${a.name}：有效期 ${a.expiry_date}${a.expired ? '（已过期，禁止使用）' : '（30 天内）'}`)}
            />
            <AlertBlock
              label="今日请检计划"
              empty="今日无待请检计划"
              items={alerts.today_plans.map((p) =>
                `${p.department} ${p.product_name}${p.batch_no ? `（批号 ${p.batch_no}）` : ''} 计划 ${p.plan_time.slice(11)}`)}
            />
          </Space>
        ) : (
          <Text type="secondary">加载中…</Text>
        )}
      </Card>

      <Space wrap>
        <Button type="primary" onClick={() => router.push('/quality/task')}>检验填报</Button>
        <Button onClick={() => router.push('/quality/summary')}>汇总统计</Button>
        <Button onClick={() => router.push('/quality/standards')}>产品标准</Button>
        <Button icon={<CheckCircleOutlined />} onClick={() => load()}>刷新</Button>
      </Space>
    </div>
  )
}
