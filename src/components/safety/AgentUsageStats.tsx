'use client'

import { useEffect, useState } from 'react'
import { Spin, Empty, Statistic, Row, Col, Card, Typography } from 'antd'
import {
  BarChartOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { getAgentUsageStats } from '@/actions/safety'
import type { AgentUsageStats as AgentUsageStatsType } from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography

const AGENT_LABELS: Record<string, string> = {
  hazard_identification: '隐患识别 Agent',
  hazard_source_identification: '危险源辨识 Agent',
  rectification_review: '整改初审 Agent',
}

interface Props {
  articleId: string
}

export default function AgentUsageStats({ articleId }: Props) {
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<AgentUsageStatsType | null>(null)

  useEffect(() => {
    if (!articleId) return
    setLoading(true)
    getAgentUsageStats(articleId)
      .then((res) => {
        if (res.code === 200 && res.data) {
          setStats(res.data)
        }
      })
      .finally(() => setLoading(false))
  }, [articleId])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    )
  }

  if (!stats) {
    return <Empty description="暂无统计数据" />
  }

  const agentEntries = Object.entries(stats.by_agent || {})

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="近30天注入"
              value={stats.total_injections_30d}
              prefix={<ThunderboltOutlined />}
              suffix="次"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="关联 Agent"
              value={agentEntries.filter(([, v]) => v > 0).length}
              prefix={<BarChartOutlined />}
              suffix="个"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="最近注入"
              value={
                stats.last_injected_at
                  ? dayjs(stats.last_injected_at).format('MM-DD HH:mm')
                  : '-'
              }
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {agentEntries.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>
            按 Agent 分类
          </Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {agentEntries.map(([agent, count]) => (
              <div
                key={agent}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 12px',
                  backgroundColor: '#fafaf9',
                  borderRadius: 6,
                  border: '1px solid #f0eeeb',
                }}
              >
                <Text>{AGENT_LABELS[agent] || agent}</Text>
                <Text strong>{count} 次</Text>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 12, color: '#a4a097', fontSize: 12 }}>
        提示：注入统计基于近30天 AI 工作流调用日志。实际使用量取决于隐患/危险源辨识的触发频率和知识卡片选中概率。
      </div>
    </div>
  )
}
