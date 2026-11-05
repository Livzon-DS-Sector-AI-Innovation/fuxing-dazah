'use client'

// 五金库盘点（二期 M4）：盘点单生成 → 手机实盘直填 → 差异表导出 →
// 差异复核 → Web 确认门（人确认才 ADJ 入账）。设计 §2.6/§十一。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined, PlusOutlined } from '@ant-design/icons'
import {
  cancelHardwareStocktakeClient,
  confirmHardwareStocktakeClient,
  createHardwareStocktakeClient,
  fetchHardwareStocktakeClient,
  fetchHardwareStocktakesClient,
  fillHardwareStocktakeItemClient,
  hardwareStocktakeExportUrl,
  reviewHardwareStocktakeClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_STOCKTAKE_STATUS_LABEL,
  HARDWARE_STOCKTAKE_TYPE_LABEL,
  type HardwareStocktakeItemRecord,
  type HardwareStocktakeRecord,
  type HardwareStocktakeStatus,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'

const STATUS_COLOR: Record<HardwareStocktakeStatus, string> = {
  draft: 'default',
  counting: 'processing',
  reviewed: 'warning',
  confirmed: 'success',
  cancelled: 'error',
}

export function HardwareStocktakeBoard() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:stocktake:manage')

  const list = useQuery({
    queryKey: ['hardware-stocktakes', status],
    queryFn: () => fetchHardwareStocktakesClient({ status, pageSize: 50 }),
    placeholderData: keepPreviousData,
  })

  const detail = useQuery({
    queryKey: ['hardware-stocktake', detailId],
    queryFn: () => fetchHardwareStocktakeClient(detailId!),
    enabled: !!detailId,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hardware-stocktakes'] })
    qc.invalidateQueries({ queryKey: ['hardware-stocktake', detailId] })
  }

  const createMut = useMutation({
    mutationFn: (v: { take_type: string; note?: string }) =>
      createHardwareStocktakeClient(v.take_type, v.note),
    onSuccess: (take) => {
      message.success(`盘点单 ${take.take_no} 已生成（快照 ${take.items ? take.items.length : ''}行）`)
      setCreateOpen(false)
      setDetailId(take.id)
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const reviewMut = useMutation({
    mutationFn: (v: { explained_by: string }) =>
      reviewHardwareStocktakeClient(detailId!, v.explained_by),
    onSuccess: () => {
      message.success('差异复核完成，待负责人确认入账')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const confirmMut = useMutation({
    mutationFn: (v: { confirmed_by: string }) =>
      confirmHardwareStocktakeClient(detailId!, v.confirmed_by),
    onSuccess: (take) => {
      message.success(`盘点调整已入账（盘盈 ${take.diff_surplus_items ?? 0} 行 / 盘亏 ${take.diff_deficit_items ?? 0} 行）`)
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelHardwareStocktakeClient(id),
    onSuccess: () => {
      message.success('盘点单已作废')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: TableColumnsType<HardwareStocktakeRecord> = [
    { title: '盘点单号', dataIndex: 'take_no', width: 170 },
    {
      title: '类型',
      dataIndex: 'take_type',
      width: 100,
      render: (v: keyof typeof HARDWARE_STOCKTAKE_TYPE_LABEL) =>
        HARDWARE_STOCKTAKE_TYPE_LABEL[v] ?? v,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: HardwareStocktakeStatus) => (
        <Tag color={STATUS_COLOR[v]}>{HARDWARE_STOCKTAKE_STATUS_LABEL[v]}</Tag>
      ),
    },
    {
      title: '差异（盈/亏/金额）',
      width: 160,
      render: (_, r) =>
        r.status === 'confirmed' || r.status === 'reviewed'
          ? `${r.diff_surplus_items ?? '-'} / ${r.diff_deficit_items ?? '-'} / ${r.diff_total_amount ?? '-'}`
          : '—',
    },
    { title: '确认人', dataIndex: 'confirmed_by', width: 100, render: (v) => v || '—' },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    {
      title: '操作',
      width: 200,
      render: (_, r) => (
        <Space size={4} wrap>
          <Button size="small" type="link" onClick={() => setDetailId(r.id)}>
            {r.status === 'draft' || r.status === 'counting' ? '去实盘' : '查看'}
          </Button>
          <Button
            size="small"
            type="link"
            href={hardwareStocktakeExportUrl(r.id)}
            target="_blank"
            icon={<DownloadOutlined />}
          >
            差异表
          </Button>
          {canManage && r.status !== 'confirmed' && r.status !== 'cancelled' && (
            <Popconfirm title="作废后不可恢复，确认作废？" onConfirm={() => cancelMut.mutate(r.id)}>
              <Button size="small" type="link" danger>
                作废
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const take = detail.data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 140 }}
          value={status}
          onChange={setStatus}
          options={Object.entries(HARDWARE_STOCKTAKE_STATUS_LABEL).map(([v, l]) => ({
            value: v,
            label: l,
          }))}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            生成盘点单
          </Button>
        )}
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={columns}
        pagination={{ total: list.data?.total ?? 0, pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
      />

      <Modal
        title="生成盘点单（book 快照自当前批次余额）"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMut.mutate({ take_type: 'monthly' })}
        confirmLoading={createMut.isPending}
        okText="生成"
      >
        <p className="text-sm text-gray-500">
          全部启用中的共用类物料逐行快照账存；期初校准（上线首次全面盘点）请选
          「期初校准」类型。
        </p>
        <Space wrap>
          <Button onClick={() => createMut.mutate({ take_type: 'monthly' })}>月度盘点</Button>
          <Button onClick={() => createMut.mutate({ take_type: 'annual' })}>年度盘点</Button>
          <Button onClick={() => createMut.mutate({ take_type: 'special' })}>专项盘点</Button>
          <Button type="primary" onClick={() => createMut.mutate({ take_type: 'calibration' })}>
            期初校准（P4 存量盘盈）
          </Button>
        </Space>
      </Modal>

      <Drawer
        title={take ? `${take.take_no}（${HARDWARE_STOCKTAKE_TYPE_LABEL[take.take_type]}）` : '盘点单'}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        width="92%"
        styles={{ body: { padding: 12 } }}
      >
        {take && (
          <StocktakeDetail
            take={take}
            items={take.items ?? []}
            canManage={canManage}
            onFilled={invalidate}
            reviewMut={reviewMut}
            confirmMut={confirmMut}
          />
        )}
      </Drawer>
    </div>
  )
}

function StocktakeDetail({
  take,
  items,
  canManage,
  onFilled,
  reviewMut,
  confirmMut,
}: {
  take: HardwareStocktakeRecord
  items: HardwareStocktakeItemRecord[]
  canManage: boolean
  onFilled: () => void
  reviewMut: ReturnType<typeof useMutation<unknown, Error, { explained_by: string }>>
  confirmMut: ReturnType<typeof useMutation<unknown, Error, { confirmed_by: string }>>
}) {
  const { message } = App.useApp()
  const editable = take.status === 'draft' || take.status === 'counting'
  const counted = items.filter((i) => i.actual_qty !== null).length
  const diffRows = items.filter((i) => i.diff_qty !== null && i.diff_qty !== 0)

  const fillMut = useMutation({
    mutationFn: (v: { item_id: string; actual_qty: number; explanation?: string }) =>
      fillHardwareStocktakeItemClient(take.id, v.item_id, v.actual_qty, v.explanation),
    onSuccess: () => {
      message.success('已记录实盘数')
      onFilled()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: TableColumnsType<HardwareStocktakeItemRecord> = [
    {
      title: '物料',
      width: 200,
      render: (_, r) => (
        <div>
          <div className="font-medium">{r.name}</div>
          <div className="text-xs text-gray-400">
            {r.code || '编码待回填'} · {r.spec || '-'} · {r.unit}
          </div>
        </div>
      ),
    },
    { title: '账存', dataIndex: 'book_qty', width: 80 },
    {
      title: '实盘',
      width: editable ? 140 : 80,
      render: (_, r) =>
        editable ? (
          <InputNumber
            size="small"
            min={0}
            defaultValue={r.actual_qty ?? undefined}
            style={{ width: 90 }}
            placeholder="实盘数"
            onPressEnter={(e) => {
              const v = Number((e.target as HTMLInputElement).value)
              if (!Number.isNaN(v)) fillMut.mutate({ item_id: r.id, actual_qty: v })
            }}
            onBlur={(e) => {
              const v = Number(e.target.value)
              if (e.target.value !== '' && !Number.isNaN(v)) {
                fillMut.mutate({ item_id: r.id, actual_qty: v })
              }
            }}
          />
        ) : (
          r.actual_qty ?? '—'
        ),
    },
    {
      title: '差异',
      dataIndex: 'diff_qty',
      width: 80,
      render: (v: number | null) =>
        v === null ? '—' : v === 0 ? '0' : <span className={v > 0 ? 'text-green-600' : 'text-red-500'}>{v}</span>,
    },
    {
      title: '差异金额',
      dataIndex: 'diff_amount',
      width: 90,
      render: (v: number | null) => (v === null ? '—' : v.toFixed(2)),
    },
    {
      title: '差异说明',
      width: editable ? 200 : 150,
      render: (_, r) =>
        editable ? (
          <Input
            size="small"
            defaultValue={r.explanation ?? undefined}
            placeholder="差异原因（选填）"
            onBlur={(e) => {
              if (e.target.value && e.target.value !== r.explanation) {
                fillMut.mutate({
                  item_id: r.id,
                  actual_qty: r.actual_qty ?? r.book_qty,
                  explanation: e.target.value,
                })
              }
            }}
          />
        ) : (
          r.explanation || '—'
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>
          实盘进度 <b>{counted}</b>/{items.length}
        </span>
        <span>
          差异行 <b className="text-orange-500">{diffRows.length}</b>
        </span>
        {take.status === 'confirmed' && (
          <span className="text-gray-500">
            已入账：盘盈 {take.diff_surplus_items} 行 / 盘亏 {take.diff_deficit_items} 行 / 金额{' '}
            {take.diff_total_amount}
          </span>
        )}
      </div>

      <Table
        rowKey="id"
        size="small"
        dataSource={items}
        columns={columns}
        pagination={{ pageSize: 30, showTotal: (t) => `共 ${t} 行` }}
        scroll={{ x: 700 }}
      />

      {canManage && (take.status === 'counting' || take.status === 'reviewed') && (
        <Space wrap>
          {take.status === 'counting' && (
            <Popconfirm
              title={`共 ${items.length - counted} 行未盘，盘完才能复核。确认全部盘完并复核？`}
              onConfirm={() => reviewMut.mutate({ explained_by: '仓管员' })}
            >
              <Button loading={reviewMut.isPending}>差异复核</Button>
            </Popconfirm>
          )}
          {take.status === 'reviewed' && (
            <Popconfirm
              title="确认入账后盘点调整立即生效（盘盈建批次/盘亏扣批次），不可撤销。确认？"
              onConfirm={() => confirmMut.mutate({ confirmed_by: '仓储负责人' })}
            >
              <Button type="primary" danger loading={confirmMut.isPending}>
                确认入账（Web 确认门）
              </Button>
            </Popconfirm>
          )}
        </Space>
      )}
    </div>
  )
}
