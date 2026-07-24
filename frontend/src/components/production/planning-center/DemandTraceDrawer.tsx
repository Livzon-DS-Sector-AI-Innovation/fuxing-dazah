'use client'

import { Drawer, Tree, Tag, Spin, Empty, Typography } from 'antd'
import {
  AimOutlined,
  ScheduleOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/http-client'
import type { TraceNode } from '@/types/production'

const { Text } = Typography

const TYPE_ICONS: Record<string, React.ReactNode> = {
  demand: <AimOutlined style={{ color: '#5645d4' }} />,
  plan_item: <ScheduleOutlined style={{ color: '#dd5b00' }} />,
  batch: <ExperimentOutlined style={{ color: '#1aae39' }} />,
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  confirmed: 'blue',
  partial: 'orange',
  fulfilled: 'green',
  closed: 'default',
  cancelled: 'red',
  draft: 'default',
  scheduled: 'blue',
  allocated: 'purple',
  in_progress: 'blue',
  completed: 'green',
}

interface Props {
  demandId: string | null
  onClose: () => void
}

function nodeToTreeData(node: TraceNode): any {
  return {
    key: `${node.type}:${node.id}`,
    title: (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12 }}>
          {TYPE_ICONS[node.type] ?? null}
        </span>
        <Text style={{ fontSize: 13 }}>{node.label}</Text>
        {node.quantity != null && (
          <Text style={{ fontSize: 12, color: '#787671' }}>
            {node.quantity}{node.unit ?? ''}
          </Text>
        )}
        {node.status && (
          <Tag
            color={STATUS_COLORS[node.status] ?? 'default'}
            style={{ fontSize: 11, lineHeight: '18px', margin: 0 }}
          >
            {node.status}
          </Tag>
        )}
      </span>
    ),
    children: node.children?.map(nodeToTreeData),
    selectable: false,
  }
}

export function DemandTraceDrawer({ demandId, onClose }: Props) {
  const { data: traceNodes, isLoading } = useQuery({
    queryKey: ['demand-trace', demandId],
    queryFn: () =>
      apiGet<TraceNode[]>(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/production/demands/${demandId}/trace`,
      ),
    enabled: !!demandId,
  })

  const treeData = traceNodes?.map(nodeToTreeData) ?? []

  return (
    <Drawer
      title="需求追溯"
      open={!!demandId}
      onClose={onClose}
      size="large"
      styles={{ body: { padding: '16px 24px' } }}
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : !traceNodes?.length ? (
        <Empty description="暂无追溯数据" />
      ) : (
        <Tree
          treeData={treeData}
          defaultExpandAll
          blockNode
          showIcon={false}
        />
      )}
    </Drawer>
  )
}
