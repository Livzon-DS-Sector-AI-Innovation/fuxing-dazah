'use client'

// 五金库月度采购计划（二期 M5）：25 日自动生成 P7 公式草案（安全库存+
// 月使用量−25日库存），人工编辑（重跑保留）、AI 用量注释（建议态）、
// 制度附件 4 表样导出。设计 §2.6/§十一。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Input,
  InputNumber,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  fetchHardwarePlanClient,
  fetchHardwarePlansClient,
  generateHardwarePlanClient,
  hardwarePlanExportUrl,
  updateHardwarePlanItemClient,
} from '@/lib/api/warehouse-hardware'
import type { HardwarePlanItemRecord, HardwarePlanRecord } from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { PageHeader } from '@/components/warehouse'

export function HardwarePlansBoard() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [detailMonth, setDetailMonth] = useState<string | null>(null)
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:plan:manage')

  const list = useQuery({
    queryKey: ['hardware-plans'],
    queryFn: () => fetchHardwarePlansClient(1, 50),
    placeholderData: keepPreviousData,
  })
  const detail = useQuery({
    queryKey: ['hardware-plan', detailMonth],
    queryFn: () => fetchHardwarePlanClient(detailMonth!),
    enabled: !!detailMonth,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hardware-plans'] })
    qc.invalidateQueries({ queryKey: ['hardware-plan', detailMonth] })
  }

  const genMut = useMutation({
    mutationFn: () => generateHardwarePlanClient(undefined, true),
    onSuccess: (plan) => {
      message.success(`次月计划草案 ${plan.plan_month} 已生成/刷新（人工编辑行保留）`)
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: TableColumnsType<HardwarePlanRecord> = [
    { title: '计划月', dataIndex: 'plan_month', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => (v === 'exported' ? <Tag color="green">已导出</Tag> : <Tag>草案</Tag>),
    },
    {
      title: 'AI 注释',
      dataIndex: 'annotated',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="blue">已注释</Tag> : <Tag>未跑/失败</Tag>),
    },
    {
      title: '快照时间',
      dataIndex: 'snapshot_at',
      width: 160,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'),
    },
    {
      title: '操作',
      width: 230,
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => setDetailMonth(r.plan_month)}>
            查看草案
          </Button>
          <Button
            size="small"
            type="link"
            icon={<DownloadOutlined />}
            href={hardwarePlanExportUrl(r.plan_month)}
            target="_blank"
          >
            表样导出
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumb={['仓储管理', '五金库', '月度采购计划']}
        title="五金月度采购计划"
        description="每月 25 日 09:00 自动生成次月草案：月采购量=安全库存+月使用量−25日库存（P7）；人工编辑重跑保留；导出制度附件 4 表样"
      />
      <div className="flex flex-wrap gap-2">
        {canManage && (
          <Popconfirm
            title="生成/重跑次月计划草案？（人工编辑行保留，其余按最新快照刷新）"
            onConfirm={() => genMut.mutate()}
          >
            <Button type="primary" icon={<ThunderboltOutlined />} loading={genMut.isPending}>
              生成/重跑次月草案
            </Button>
          </Popconfirm>
        )}
        <Button
          icon={<ReloadOutlined />}
          onClick={() => invalidate()}
        >
          刷新
        </Button>
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={columns}
        pagination={{ total: list.data?.total ?? 0, pageSize: 20 }}
      />

      <Drawer
        title={detailMonth ? `${detailMonth} 计划草案` : ''}
        open={!!detailMonth}
        onClose={() => setDetailMonth(null)}
        width="94%"
        styles={{ body: { padding: 12 } }}
      >
        {detail.data && (
          <PlanDetail
            plan={detail.data}
            items={detail.data.items ?? []}
            canManage={canManage}
            onChanged={invalidate}
          />
        )}
      </Drawer>
    </div>
  )
}

function PlanDetail({
  plan,
  items,
  canManage,
  onChanged,
}: {
  plan: HardwarePlanRecord
  items: HardwarePlanItemRecord[]
  canManage: boolean
  onChanged: () => void
}) {
  const { message } = App.useApp()
  const editable = canManage && plan.status === 'draft'

  const editMut = useMutation({
    mutationFn: (v: { id: string; purchase_qty?: number; remark?: string }) =>
      updateHardwarePlanItemClient(plan.plan_month, v.id, {
        purchase_qty: v.purchase_qty,
        remark: v.remark,
      }),
    onSuccess: () => {
      message.success('已保存（人工编辑，重跑保留）')
      onChanged()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const diffCount = items.filter((i) => i.is_edited).length
  const columns: TableColumnsType<HardwarePlanItemRecord> = [
    {
      title: '物料',
      width: 190,
      render: (_, r) => (
        <div>
          <div className="font-medium">
            {r.name}
            {r.is_edited && (
              <Tag color="orange" className="ml-1">
                已编辑
              </Tag>
            )}
          </div>
          <div className="text-xs text-gray-400">
            {r.code || '编码待回填'} · {r.spec || '-'} · {r.unit}
          </div>
        </div>
      ),
    },
    { title: '月需求合计', dataIndex: 'monthly_demand_total', width: 90 },
    { title: '安全库存', dataIndex: 'safety_stock', width: 85 },
    { title: '25日库存', dataIndex: 'stock_on_25th', width: 85 },
    { title: '月使用量', dataIndex: 'monthly_usage', width: 85 },
    {
      title: '月度采购量',
      width: editable ? 130 : 95,
      render: (_, r) =>
        editable ? (
          <InputNumber
            size="small"
            min={0}
            defaultValue={r.purchase_qty}
            style={{ width: 100 }}
            onBlur={(e) => {
              const v = Number(e.target.value)
              if (e.target.value !== '' && !Number.isNaN(v) && v !== r.purchase_qty) {
                editMut.mutate({ id: r.id, purchase_qty: v })
              }
            }}
          />
        ) : (
          r.purchase_qty
        ),
    },
    {
      title: 'AI 注释',
      dataIndex: 'ai_note',
      width: 200,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <span className="text-xs text-blue-600">{v.slice(0, 40)}…</span>
          </Tooltip>
        ) : (
          <span className="text-xs text-gray-300">—</span>
        ),
    },
    {
      title: '备注',
      dataIndex: 'remark',
      width: 150,
      render: (_, r) =>
        editable ? (
          <Input
            size="small"
            defaultValue={r.remark ?? undefined}
            onBlur={(e) => {
              if (e.target.value !== (r.remark ?? '')) {
                editMut.mutate({ id: r.id, purchase_qty: r.purchase_qty, remark: e.target.value })
              }
            }}
          />
        ) : (
          r.remark || '—'
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="text-sm text-gray-500">
        快照 {plan.snapshot_at ? new Date(plan.snapshot_at).toLocaleString('zh-CN', { hour12: false }) : '—'}
        ；人工编辑 {diffCount} 行（同月重跑保留）；AI 注释为建议态，不改数量。
      </div>
      <Table
        rowKey="id"
        size="small"
        dataSource={items}
        columns={columns}
        pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 行` }}
        scroll={{ x: 1050 }}
      />
    </div>
  )
}
