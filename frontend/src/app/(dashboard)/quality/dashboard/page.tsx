'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Card, Row, Col, Statistic, List, Tag, Button, App, Space, Progress } from 'antd'
import {
  CalendarOutlined, SearchOutlined, LoadingOutlined, CheckCircleOutlined, SunOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import dayjs from 'dayjs'
import type { QualityDashboard, DailyReportItem } from '@/types/quality'
import { fetchQualityDashboard, fetchDailyReports } from '@/actions/quality'

const { Title, Paragraph, Text } = Typography

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  in_progress: { label: '填报中', color: 'processing' },
  pending_review: { label: '待复核', color: 'warning' },
  completed: { label: '已完成', color: 'success' },
  void: { label: '已作废', color: 'default' },
}

type DashRow = QualityDashboard['today'][number]

function TaskItem({ t, color }: { t: DashRow; color?: string }) {
  const router = useRouter()
  const pct = t.total ? Math.round((t.filled / t.total) * 100) : 0
  return (
    <List.Item style={{ cursor: 'pointer', paddingBlock: 6 }}
      onClick={() => router.push(`/quality/task/${t.task_id}`)}>
      <div style={{ width: '100%' }}>
        <Space wrap size={6}>
          {color && <CheckCircleOutlined style={{ color }} />}
          <Text strong>{t.product_name}</Text>
          <Text type="secondary">批号 {t.batch_number}</Text>
          <Tag color={STATUS_LABEL[t.status]?.color}>{STATUS_LABEL[t.status]?.label ?? t.status}</Tag>
          {t.report_date && <Text type="secondary">出报 {t.report_date}</Text>}
        </Space>
        <Progress percent={pct} size="small" format={() => `${t.filled}/${t.total}`}
          style={{ marginTop: 2, marginBottom: 0 }} />
      </div>
    </List.Item>
  )
}

export default function QualityDashboardPage() {
  const router = useRouter()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<QualityDashboard | null>(null)
  const [dailyReports, setDailyReports] = useState<DailyReportItem[]>([])

  const today = dayjs().format('YYYY-MM-DD')
  const tomorrow = dayjs().add(1, 'day').format('YYYY-MM-DD')

  const load = useCallback(async (silent = false) => {
    try {
      const [res, reports] = await Promise.all([
        fetchQualityDashboard(),
        fetchDailyReports(),
      ])
      setData(res.data)
      setDailyReports(reports.data || [])
    } catch (err: any) {
      // 自动刷新静默失败（此前后端异常时每 30 秒弹一条错误轰炸）
      if (!silent) message.error(err.message || '加载总览失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { load() }, [load])

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
        <Title level={3} style={{ marginBottom: 4 }}>📊 质量总览</Title>
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          今日出报、待复核、在途批次一屏总览；点条目直达任务详情，页面每 30 秒自动刷新。
        </Paragraph>
      </div>

      <Row gutter={16}>
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
              valueStyle={{ color: (data?.pending_review_count ?? 0) > 0 ? '#faad14' : undefined }} />
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

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card size="small" title="📅 今日出报任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部</Button>}>
            <List size="small" dataSource={data?.today || []} locale={{ emptyText: '今日无出报任务' }}
              renderItem={(t) => <TaskItem t={t} />} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="🔍 待复核（需两名复核人通过）"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task?status=pending_review')}>全部</Button>}>
            <List size="small" dataSource={data?.pending_review || []} locale={{ emptyText: '暂无待复核任务' }}
              renderItem={(t) => <TaskItem t={t} />} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="✅ 最近完成任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部</Button>}>
            <List size="small" dataSource={data?.recent_completed || []} locale={{ emptyText: '暂无完成任务' }}
              renderItem={(t) => <TaskItem t={t} color="#0ca30c" />} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="📄 今日报告单（流水号+产品+批号）"
        extra={<Button size="small" type="link" onClick={() => router.push('/quality/report')}>报告单页</Button>}>
        <List
          size="small"
          dataSource={dailyReports}
          locale={{ emptyText: '今日暂无生成报告单' }}
          renderItem={(r) => (
            <List.Item>
              <Space wrap size={8}>
                <Text strong>{r.serial_no}</Text>
                <Text>{r.product_name}</Text>
                <Text type="secondary">批号 {r.batch_number}</Text>
                <Text type="secondary">{r.created_at}</Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Space wrap>
        <Button type="primary" onClick={() => router.push('/quality/task')}>📝 检验填报</Button>
        <Button onClick={() => router.push('/quality/summary')}>📈 汇总统计</Button>
        <Button onClick={() => router.push('/quality/standards')}>🎯 产品标准</Button>
        <Button icon={<CheckCircleOutlined />} onClick={() => load()}>刷新</Button>
      </Space>
    </div>
  )
}
