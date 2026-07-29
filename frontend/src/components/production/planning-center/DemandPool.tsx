'use client'

import { useState } from 'react'
import { Table, Button, Space, Tag, Select, Input, App } from 'antd'
import type { TableProps } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usePermission } from '@/hooks/usePermission'
import { apiFetchPaginated } from '@/lib/http-client'
import type { Demand } from '@/types/production'
import { confirmDemand, cancelDemand } from '@/actions/production'
import { DemandFormModal } from './DemandFormModal'
import { DemandTraceDrawer } from './DemandTraceDrawer'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'red', high: 'orange', medium: 'gold', low: 'blue',
}
const STATUS_COLORS: Record<string, string> = {
  pending: 'default', confirmed: 'blue', partial: 'orange',
  fulfilled: 'green', closed: 'default', cancelled: 'red',
}
const SOURCE_LABELS: Record<string, string> = {
  manual: '手动', sales_order: '订单', forecast: '预测', internal: '内部',
}
const PRIORITY_LABELS: Record<string, string> = {
  urgent: '紧急', high: '高', medium: '中', low: '低',
}
const STATUS_LABELS: Record<string, string> = {
  pending: '待确认', confirmed: '已确认', partial: '部分',
  fulfilled: '已完成', closed: '已关闭', cancelled: '已取消',
}

export function DemandPool() {
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:batch:submit')
  const queryClient = useQueryClient()
  const { message } = App.useApp()

  const [filters, setFilters] = useState<Record<string, string | undefined>>({})
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editingDemand, setEditingDemand] = useState<Demand | null>(null)
  const [traceId, setTraceId] = useState<string | null>(null)

  const qs = (): string => {
    const sp = new URLSearchParams({ page: String(page), page_size: '20' })
    for (const [k, v] of Object.entries(filters)) {
      if (v) sp.set(k, v)
    }
    return sp.toString()
  }

  const { data, isLoading } = useQuery({
    queryKey: ['demands', filters, page],
    queryFn: () =>
      apiFetchPaginated<Demand>(`${API_BASE}/api/v1/production/demands?${qs()}`),
  })

  const confirmMut = useMutation({
    mutationFn: async (id: string) => {
      const result = await confirmDemand(id)
      if (!result.success) throw new Error(result.error)
      return result.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['demands'] })
      message.success('已确认')
    },
    onError: (err: Error) => message.error(err.message),
  })

  const cancelMut = useMutation({
    mutationFn: async (id: string) => {
      const result = await cancelDemand(id)
      if (!result.success) throw new Error(result.error)
      return result.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['demands'] })
      message.success('已取消')
    },
    onError: (err: Error) => message.error(err.message),
  })

  const columns: TableProps<Demand>['columns'] = [
    { title: '需求编号', dataIndex: 'demand_no', width: 180 },
    {
      title: '来源', dataIndex: 'source_type', width: 80,
      render: (v: string) => SOURCE_LABELS[v] || v,
    },
    { title: '产品', dataIndex: 'product_name', width: 140 },
    {
      title: '需求量', width: 80,
      render: (_: unknown, r: Demand) => `${r.demanded_quantity}${r.unit}`,
    },
    {
      title: '已分配', width: 80,
      render: (_: unknown, r: Demand) => `${r.allocated_quantity}${r.unit}`,
    },
    {
      title: '剩余', width: 80,
      render: (_: unknown, r: Demand) => `${Math.max(0, r.demanded_quantity - r.allocated_quantity)}${r.unit}`,
    },
    { title: '交期', dataIndex: 'demand_date', width: 100 },
    {
      title: '优先级', dataIndex: 'priority', width: 70,
      render: (v: string) => <Tag color={PRIORITY_COLORS[v]}>{PRIORITY_LABELS[v] || v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 70,
      render: (v: string) => <Tag color={STATUS_COLORS[v]}>{STATUS_LABELS[v] || v}</Tag>,
    },
    {
      title: '操作', width: 200,
      render: (_: unknown, record: Demand) => (
        <Space>
          {canSubmit && record.status === 'pending' && (
            <Button size="small" type="link" loading={confirmMut.isPending} onClick={() => confirmMut.mutate(record.id)}>确认</Button>
          )}
          {canSubmit && record.status !== 'cancelled' && record.status !== 'closed' && (
            <Button size="small" type="link" danger loading={cancelMut.isPending} onClick={() => cancelMut.mutate(record.id)}>取消</Button>
          )}
          <Button size="small" type="link" onClick={() => setTraceId(record.id)}>追溯</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        {canSubmit && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingDemand(null); setFormOpen(true) }}>
            新建需求
          </Button>
        )}
        <Select
          allowClear
          placeholder="来源"
          style={{ width: 100 }}
          onChange={v => { setFilters(f => ({ ...f, source_type: v })); setPage(1) }}
          options={[
            { value: 'manual', label: '手动' },
            { value: 'sales_order', label: '订单' },
            { value: 'forecast', label: '预测' },
          ]}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 100 }}
          onChange={v => { setFilters(f => ({ ...f, status: v })); setPage(1) }}
          options={[
            { value: 'pending', label: '待确认' },
            { value: 'confirmed', label: '已确认' },
            { value: 'partial', label: '部分' },
            { value: 'fulfilled', label: '已完成' },
          ]}
        />
        <Input
          allowClear
          placeholder="搜索编号/产品"
          prefix={<SearchOutlined />}
          style={{ width: 200 }}
          onChange={e => { setFilters(f => ({ ...f, keyword: e.target.value || undefined })); setPage(1) }}
        />
      </div>
      <Table<Demand>
        columns={columns}
        dataSource={data?.items ?? []}
        loading={isLoading}
        rowKey="id"
        size="middle"
        pagination={{
          current: page,
          total: data?.total ?? 0,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />
      <DemandFormModal open={formOpen} demand={editingDemand} onClose={() => setFormOpen(false)} />
      <DemandTraceDrawer demandId={traceId} onClose={() => setTraceId(null)} />
    </div>
  )
}
