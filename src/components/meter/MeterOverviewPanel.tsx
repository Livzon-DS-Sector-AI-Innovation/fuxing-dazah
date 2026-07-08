'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Card, Col, Row, Segmented, Statistic } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  StopOutlined,
  WarningOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import { MeterOverview } from '@/types/meter'
import { getMeterOverview } from '@/actions/meter'

const CARD_STYLE: React.CSSProperties = { textAlign: 'center' }

export function MeterOverviewPanel() {
  const { message } = App.useApp()
  const [source, setSource] = useState<'instrument' | 'gas_detector'>('instrument')
  const [data, setData] = useState<MeterOverview | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const stats = await getMeterOverview(source)
      setData(stats)
    } catch {
      message.error('获取总览数据失败')
    } finally {
      setLoading(false)
    }
  }, [source, message])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>仪表总览</h2>
        <Segmented
          value={source}
          onChange={(v) => setSource(v as 'instrument' | 'gas_detector')}
          options={[
            { label: '标准计量器具', value: 'instrument' },
            { label: '有毒有害可燃探测器', value: 'gas_detector' },
          ]}
        />
      </div>

      {/* 第一排：总数 + 状态分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="总数量"
              value={data?.total ?? 0}
              prefix={<DashboardOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="在用"
              value={data?.in_use ?? 0}
              styles={{ content: { color: '#52c41a' } }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="超期"
              value={data?.overdue ?? 0}
              styles={{ content: { color: '#fa8c16' } }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="停用"
              value={data?.stopped ?? 0}
              styles={{ content: { color: '#ff4d4f' } }}
              prefix={<StopOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 第二排：到期提醒 */}
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="截止今天到期"
              value={data?.due_today ?? 0}
              styles={{ content: { color: data?.due_today ? '#ff4d4f' : undefined } }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="未来 7 天到期"
              value={data?.due_7d ?? 0}
              styles={{ content: { color: data?.due_7d ? '#fa8c16' : undefined } }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="未来 30 天到期"
              value={data?.due_30d ?? 0}
              styles={{ content: { color: data?.due_30d ? '#faad14' : undefined } }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card loading={loading} style={CARD_STYLE}>
            <Statistic
              title="未来 90 天到期"
              value={data?.due_90d ?? 0}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
