'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Card, Row, Col, Statistic, List, Tag, Button, App, Space } from 'antd'
import {
  CalendarOutlined, SearchOutlined, LoadingOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import type { QualityDashboard } from '@/types/quality'
import { fetchQualityDashboard } from '@/actions/quality'

const { Title, Paragraph, Text } = Typography

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  in_progress: { label: '填报中', color: 'processing' },
  pending_review: { label: '待复核', color: 'warning' },
  completed: { label: '已完成', color: 'success' },
  void: { label: '已作废', color: 'default' },
}

export default function QualityDashboardPage() {
  const router = useRouter()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<QualityDashboard | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchQualityDashboard()
      setData(res.data)
    } catch (err: any) {
      message.error(err.message || '加载总览失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { load() }, [load, reloadKey])

  return (
    <div className="space-y-4">
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>📊 质量总览</Title>
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          今日出报、待复核、在途批次一屏总览；点条目直达任务详情。
        </Paragraph>
      </div>

      <Row gutter={16}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small" loading={loading}>
            <Statistic title="今日出报" value={data?.today.length ?? 0} prefix={<CalendarOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small" loading={loading}>
            <Statistic title="待复核" value={data?.pending_review_count ?? 0}
              prefix={<SearchOutlined />}
              valueStyle={{ color: (data?.pending_review_count ?? 0) > 0 ? '#faad14' : undefined }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small" loading={loading}>
            <Statistic title="在途（填报中）" value={data?.in_progress_count ?? 0} prefix={<LoadingOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Card size="small" title="📅 今日出报任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部任务</Button>}>
            <List
              size="small"
              dataSource={data?.today || []}
              locale={{ emptyText: '今日无出报任务' }}
              renderItem={(t) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => router.push(`/quality/task/${t.task_id}`)}
                >
                  <Space wrap>
                    <Text strong>{t.product_name}</Text>
                    <Text type="secondary">批号 {t.batch_number}</Text>
                    <Tag color={STATUS_LABEL[t.status]?.color}>{STATUS_LABEL[t.status]?.label ?? t.status}</Tag>
                    <Text type="secondary">已填 {t.filled}/{t.total}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small" title="✅ 最近完成任务"
            extra={<Button size="small" type="link" onClick={() => router.push('/quality/task')}>全部任务</Button>}>
            <List
              size="small"
              dataSource={data?.recent_completed || []}
              locale={{ emptyText: '暂无完成任务' }}
              renderItem={(t) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => router.push(`/quality/task/${t.task_id}`)}
                >
                  <Space wrap>
                    <CheckCircleOutlined style={{ color: '#0ca30c' }} />
                    <Text strong>{t.product_name}</Text>
                    <Text type="secondary">批号 {t.batch_number}</Text>
                    <Text type="secondary">出报 {t.report_date || '-'}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Space wrap>
        <Button type="primary" onClick={() => router.push('/quality/task')}>📝 检验填报</Button>
        <Button onClick={() => router.push('/quality/summary')}>📈 汇总统计</Button>
        <Button onClick={() => router.push('/quality/standards')}>🎯 产品标准</Button>
        <Button icon={<CheckCircleOutlined />} onClick={() => setReloadKey((k) => k + 1)}>刷新</Button>
      </Space>
    </div>
  )
}
