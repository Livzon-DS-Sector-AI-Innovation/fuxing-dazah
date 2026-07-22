'use client'

import { useState } from 'react'
import { Badge, Empty, Select, Space, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import {
  fetchNodeExecutionsClient,
  fetchRouteGraphClient,
  fetchRoutesClient,
} from '@/lib/api/production-client'
import type { NodeExecutionListItem } from '@/types/production'
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer'

const EXEC_STATUS_META: Record<string, { color: string; label: string }> = {
  in_progress: { color: 'blue', label: '进行中' },
  completed: { color: 'green', label: '已完成' },
  aborted: { color: 'default', label: '已中止' },
}

export function NodeExecutionsTable({ productId }: { productId: string }) {
  const [routeId, setRouteId] = useState<string | null>(null)
  const [nodeId, setNodeId] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ field: string; order: 'asc' | 'desc' } | undefined>()
  const [detail, setDetail] = useState<NodeExecutionListItem | null>(null)

  const { data: routes } = useQuery({
    queryKey: ['production-routes', productId],
    queryFn: () => fetchRoutesClient(productId),
  })
  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId!),
    enabled: !!routeId,
  })
  const { data, isLoading } = useQuery({
    queryKey: ['production-node-executions', nodeId, page, sort],
    queryFn: () =>
      fetchNodeExecutionsClient(nodeId!, { page, order_by: sort?.field, order: sort?.order }),
    enabled: !!nodeId,
  })

  const handleTableChange: TableProps<NodeExecutionListItem>['onChange'] = (
    _,
    __,
    sorter,
    extra,
  ) => {
    if (extra.action !== 'sort') return
    const s = Array.isArray(sorter) ? sorter[0] : sorter
    setSort(
      s?.order
        ? { field: String(s.field), order: s.order === 'ascend' ? 'asc' : 'desc' }
        : undefined,
    )
    setPage(1)
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="选择路线版本"
          style={{ width: 200 }}
          value={routeId}
          onChange={v => {
            setRouteId(v)
            setNodeId(null)
            setPage(1)
          }}
          options={(routes ?? []).map(r => ({
            value: r.id,
            label: `V${r.version} · ${r.name}（${
              { draft: '草稿', published: '已发布', archived: '已归档' }[r.status]
            }）`,
          }))}
        />
        <Select
          placeholder="选择工序节点"
          style={{ width: 220 }}
          value={nodeId}
          disabled={!routeId}
          onChange={v => {
            setNodeId(v)
            setPage(1)
          }}
          options={(graph?.nodes ?? []).map(n => ({
            value: n.id,
            label: `${n.name}（${n.node_code}）`,
          }))}
        />
      </Space>
      {!nodeId ? (
        <Empty description="请选择路线版本和工序节点" style={{ marginTop: 60 }} />
      ) : (
        <Table<NodeExecutionListItem>
          size="small"
          rowKey="id"
          loading={isLoading}
          dataSource={data?.items}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total,
            onChange: setPage,
            showSizeChanger: false,
          }}
          onRow={record => ({
            onClick: () => setDetail(record),
            style: { cursor: 'pointer' },
          })}
          onChange={handleTableChange}
          columns={[
            { title: '批号', dataIndex: 'batch_no', width: 180, sorter: true },
            { title: '次数', dataIndex: 'execution_seq', width: 60 },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v: string) => (
                <Tag color={EXEC_STATUS_META[v]?.color}>{EXEC_STATUS_META[v]?.label ?? v}</Tag>
              ),
            },
            { title: '负责人', dataIndex: 'owner_name', width: 100, render: v => v ?? '—' },
            {
              title: '开始时间',
              dataIndex: 'started_at',
              width: 160,
              sorter: true,
              render: (v: string) => new Date(v).toLocaleString('zh-CN'),
            },
            {
              title: '结束时间',
              dataIndex: 'finished_at',
              width: 160,
              render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN') : '—'),
            },
            {
              title: '异常',
              dataIndex: 'abnormal_count',
              width: 70,
              render: (v: number) => (v > 0 ? <Badge count={v} /> : '—'),
            },
            {
              title: '偏离',
              dataIndex: 'is_deviation',
              width: 60,
              render: (v: boolean) => (v ? <Tag color="warning">偏离</Tag> : '—'),
            },
          ]}
        />
      )}
      {detail && (
        <ExecutionDetailDrawer item={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  )
}
