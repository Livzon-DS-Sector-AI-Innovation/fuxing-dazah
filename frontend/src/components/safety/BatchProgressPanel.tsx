'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Table, Tag, Progress, Typography, Spin, Tooltip } from 'antd'
import {
  ClusterOutlined,
  RightOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  EditOutlined,
} from '@ant-design/icons'
import { getHazardIdentifications } from '@/actions/safety'
import type { HazardIdentification } from '@/types/safety'
import {
  AI_NODE_PROGRESS_OPTIONS,
  OVERALL_STATUS_OPTIONS_HI,
} from '@/types/safety'

const { Text, Title } = Typography

interface BatchProgressPanelProps {
  batchId: string
  onSelectRecord?: (id: string) => void
}

const NODE_LABELS: Record<string, { label: string; step: number }> = {}
AI_NODE_PROGRESS_OPTIONS.forEach((o, i) => {
  NODE_LABELS[o.value] = { label: o.label, step: i }
})

function getProgressStep(node: string): number {
  return NODE_LABELS[node]?.step ?? 0
}

function getProgressLabel(node: string): string {
  return NODE_LABELS[node]?.label ?? node
}

export default function BatchProgressPanel({
  batchId,
  onSelectRecord,
}: BatchProgressPanelProps) {
  const router = useRouter()
  const [records, setRecords] = useState<HazardIdentification[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const res = await getHazardIdentifications({
          batch_id: batchId,
          page_size: 100,
        })
        if (res.code === 200 && res.data) {
          const items = (res.data as HazardIdentification[]) || []
          setRecords(items)
          setTotal(res.meta?.total || items.length)
        }
      } catch {
        // 静默
      } finally {
        setLoading(false)
      }
    }
    if (batchId) load()
  }, [batchId])

  if (loading) {
    return (
      <Card size="small">
        <Spin description="加载批次进度..." />
      </Card>
    )
  }

  if (records.length === 0) {
    return null
  }

  const completedCount = records.filter(
    (r) => r.overall_status === 'completed'
  ).length
  const inProgressCount = records.filter(
    (r) => r.overall_status === 'in_progress'
  ).length
  const draftCount = records.filter(
    (r) => r.overall_status === 'draft'
  ).length

  const totalSteps = records.length * 7 // 7 scripts per record
  const completedSteps = records.reduce((sum, r) => {
    const step = getProgressStep(r.ai_node_progress)
    return sum + Math.max(0, step - 1) // pending_input=0, pending_script1=1, ..., completed=9
  }, 0)
  const progressPercent =
    totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0

  const handleViewRecord = (id: string) => {
    if (onSelectRecord) {
      onSelectRecord(id)
    } else {
      router.push(`/safety/hazard-identification/${id}`)
    }
  }

  const regulationName = records[0]?.regulation_name || ''
  const stageCount = records.length

  const columns = [
    {
      title: '#',
      width: 40,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: '工艺阶段',
      dataIndex: 'stage_name',
      key: 'stage_name',
      render: (name: string) => (
        <Text strong>{name || records.find((r) => r.stage_name === name)?.production_step || '-'}</Text>
      ),
    },
    {
      title: '当前节点',
      dataIndex: 'ai_node_progress',
      key: 'ai_node_progress',
      width: 150,
      render: (node: string) => (
        <Tag
          color={
            node === 'completed'
              ? 'green'
              : node === 'pending_input'
              ? 'default'
              : 'blue'
          }
        >
          {getProgressLabel(node)}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'overall_status',
      key: 'overall_status',
      width: 80,
      render: (status: string) => {
        const opts: Record<string, { color: string; label: string }> = {
          draft: { color: 'default', label: '草稿' },
          in_progress: { color: 'processing', label: '进行中' },
          completed: { color: 'green', label: '已完成' },
          cancelled: { color: 'red', label: '已取消' },
        }
        const o = opts[status] || { color: 'default', label: status }
        return <Tag color={o.color}>{o.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_: unknown, record: HazardIdentification) => (
        <Tooltip title="查看详情">
          <a onClick={() => handleViewRecord(record.id)}>
            <RightOutlined />
          </a>
        </Tooltip>
      ),
    },
  ]

  return (
    <Card
      size="small"
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ClusterOutlined style={{ color: '#5645d4' }} />
          <Text strong>
            批次辨识进度
            {regulationName && (
              <Text type="secondary" style={{ fontWeight: 400, marginLeft: 8 }}>
                — {regulationName}
              </Text>
            )}
          </Text>
        </span>
      }
      style={{ marginBottom: 16 }}
    >
      {/* Summary row */}
      <div
        style={{
          display: 'flex',
          gap: 24,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <Text type="secondary">工段总数</Text>
          <div>
            <Text strong style={{ fontSize: 18 }}>
              {stageCount}
            </Text>
          </div>
        </div>
        <div>
          <Text type="secondary">已完成</Text>
          <div>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
            <Text strong style={{ fontSize: 18, color: '#52c41a' }}>
              {completedCount}
            </Text>
          </div>
        </div>
        <div>
          <Text type="secondary">进行中</Text>
          <div>
            <SyncOutlined style={{ color: '#1677ff', marginRight: 4 }} />
            <Text strong style={{ fontSize: 18, color: '#1677ff' }}>
              {inProgressCount}
            </Text>
          </div>
        </div>
        <div>
          <Text type="secondary">草稿</Text>
          <div>
            <EditOutlined style={{ color: '#8c8c8c', marginRight: 4 }} />
            <Text strong style={{ fontSize: 18 }}>
              {draftCount}
            </Text>
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 150, textAlign: 'right' }}>
          <Text type="secondary">总进度</Text>
          <Progress
            percent={progressPercent}
            size="small"
            status={progressPercent === 100 ? 'success' : 'active'}
          />
        </div>
      </div>

      <Table
        dataSource={records}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
        scroll={{ y: 300 }}
      />
    </Card>
  )
}
