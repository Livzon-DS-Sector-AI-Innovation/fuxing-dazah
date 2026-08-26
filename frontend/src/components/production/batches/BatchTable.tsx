'use client'

import { useState } from 'react'
import { Badge, Button, Input, Select, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { fetchBatchesClient, fetchRoutesClient } from '@/lib/api/production-client'
import { formatDateTime } from '@/lib/utils'
import type { ProductionBatch } from '@/types/production'

export const BATCH_STATUS_META: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  scheduled: { color: 'blue', label: '已排程' },
  released: { color: 'cyan', label: '已下达' },
  pending: { color: 'default', label: '待开工' },
  in_progress: { color: 'blue', label: '生产中' },
  completed: { color: 'green', label: '已完成' },
  cancelled: { color: 'red', label: '已报废' },
}

interface Props {
  productId: string
  canSubmit: boolean
  onCreate: () => void
  onOpenDetail: (batchId: string) => void
}

export function BatchTable({ productId, canSubmit, onCreate, onOpenDetail }: Props) {
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [entryNodeFilter, setEntryNodeFilter] = useState<string | undefined>()
  const [routeFilter, setRouteFilter] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ field: string; order: 'asc' | 'desc' } | undefined>()

  const { data: routes } = useQuery({
    queryKey: ['production-routes', productId],
    queryFn: () => fetchRoutesClient(productId),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['production-batches', productId, { status, keyword, entryNodeFilter, routeFilter, page, sort }],
    queryFn: () =>
      fetchBatchesClient({
        product_id: productId,
        status,
        keyword: keyword || undefined,
        entry_node_filter: entryNodeFilter,
        route_id: routeFilter,
        page,
        order_by: sort?.field,
        order: sort?.order,
      }),
  })

  const handleTableChange: TableProps<ProductionBatch>['onChange'] = (_, __, sorter, extra) => {
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
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 130 }}
          value={status}
          onChange={v => {
            setStatus(v)
            setPage(1)
          }}
          options={Object.entries(BATCH_STATUS_META).map(([v, m]) => ({
            value: v,
            label: m.label,
          }))}
        />
        <Select
          allowClear
          placeholder="入口工序"
          style={{ width: 130 }}
          value={entryNodeFilter}
          onChange={v => {
            setEntryNodeFilter(v)
            setPage(1)
          }}
          options={[
            { value: 'root', label: '起始批次' },
            { value: 'derived', label: '衍生批次' },
          ]}
        />
        <Select
          allowClear
          placeholder="工艺路线"
          style={{ width: 200 }}
          value={routeFilter}
          onChange={v => {
            setRouteFilter(v)
            setPage(1)
          }}
          options={(routes ?? []).map(r => ({ value: r.id, label: r.route_name }))}
        />
        <Input
          allowClear
          style={{ width: 220 }}
          prefix={<SearchOutlined style={{ color: '#787671' }} />}
          placeholder="搜索批号"
          value={keyword}
          onChange={e => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
        <div style={{ flex: 1 }} />
        {canSubmit && (
          <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
            新建批次
          </Button>
        )}
      </div>
      <Table<ProductionBatch>
        size="small"
        rowKey="id"
        loading={isLoading}
        dataSource={data?.items}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize: 20,
          total: data?.total,
          onChange: setPage,
          showSizeChanger: false,
        }}
        onRow={record => ({
          onClick: () => onOpenDetail(record.id),
          style: { cursor: 'pointer' },
        })}
        onChange={handleTableChange}
        columns={[
          { title: '批号', dataIndex: 'batch_no', width: 180, sorter: true },
          {
            title: '工艺路线',
            width: 140,
            render: (_, r) => r.route_name || '—',
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 100,
            render: (v: string) => (
              <Tag
                color={BATCH_STATUS_META[v]?.color}
                className={v === 'in_progress' ? 'tag-production-active' : undefined}
              >
                {BATCH_STATUS_META[v]?.label ?? v}
              </Tag>
            ),
          },
          {
            title: '数量',
            width: 120,
            render: (_, r) => (r.quantity != null ? `${r.quantity} ${r.unit ?? ''}` : '—'),
          },
          {
            title: '入口工序',
            width: 120,
            render: (_, r) =>
              r.entry_node_id ? (
                <Badge status="processing" text="衍生批次" />
              ) : (
                <Badge status="default" text="起始批次" />
              ),
          },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            width: 170,
            sorter: true,
            render: (v: string) => new Date(v).toLocaleString('zh-CN'),
          },
          {
            title: '首工序开始',
            dataIndex: 'first_started_at',
            width: 170,
            render: (v: string | null) => formatDateTime(v),
          },
          {
            title: '末工序结束',
            dataIndex: 'last_finished_at',
            width: 170,
            render: (v: string | null) => formatDateTime(v),
          },
          { title: '备注', dataIndex: 'remark', ellipsis: true },
        ]}
      />
    </div>
  )
}
