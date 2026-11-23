'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type Key } from 'react'
import {
  App,
  Button,
  Input,
  Segmented,
  Select,
  Table,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchHardwareErpReceiptsClient,
  fetchHardwareMovementsClient,
  fetchHardwareReconcileDiffsClient,
  hardwareMovementsExportUrl,
  markHardwareMovementsEnteredClient,
  reconcileHardwareReceiptClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_MOVEMENT_BIZ_LABEL,
  HARDWARE_RECEIPT_STATUS_LABEL,
  HARDWARE_RECONCILE_STATUS_LABEL,
  type HardwareMovementDirection,
  type HardwareMovementRecord,
  type HardwareReceiptRecord,
  type HardwareReceiptStatus,
  type HardwareReconcileDiffs,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { formatQty } from './format'
import { ERP_STATUS_TONE, MOVEMENT_DIRECTION_LABEL, MOVEMENT_DIRECTION_TONE, RECONCILE_STATUS_TONE } from './constants'
import { EmptyGuide, QueryFilter, SectionCard, StatusTag } from '@/components/warehouse'

export function ErpInboundReconcilePanel() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [reconcileStatus, setReconcileStatus] = useState<string | undefined>(undefined)
  const [autoOnly, setAutoOnly] = useState(false)

  const list = useQuery({
    queryKey: ['hardware-erp-in-receipts', reconcileStatus],
    queryFn: () => fetchHardwareErpReceiptsClient({ reconcile_status: reconcileStatus }),
    placeholderData: keepPreviousData,
  })
  const diffs = useQuery({
    queryKey: ['hardware-erp-reconcile-diffs'],
    queryFn: () => fetchHardwareReconcileDiffsClient(30),
  })

  const reconcileMut = useMutation({
    mutationFn: (id: string) => reconcileHardwareReceiptClient(id),
    onSuccess: (r) => {
      message.success(
        r.reconcile_status === 'verified' ? '对账匹配成功（双向核对通过）' : `匹配状态：${r.reconcile_status}`,
      )
      qc.invalidateQueries({ queryKey: ['hardware-erp-in-receipts'] })
      qc.invalidateQueries({ queryKey: ['hardware-erp-reconcile-diffs'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="差异清单 · ERP 有 / 系统无" description="ERP 导入单未匹配到既有入库单——可人工确认入账补录（生成批次占库存）。">
          <Table
            rowKey="receipt_id"
            size="middle"
            loading={diffs.isLoading}
            dataSource={diffs.data?.erp_only ?? []}
            pagination={false}
            scroll={{ y: 240 }}
            columns={[
              { title: '单号', dataIndex: 'receipt_no', width: 170, className: 'font-mono' },
              { title: 'ERP 单号', dataIndex: 'erp_doc_no', width: 140, className: 'font-mono' },
              { title: '供应商', dataIndex: 'supplier_name', ellipsis: true },
              {
                title: '操作',
                key: 'op',
                width: 90,
                render: (_, r) => (
                  <Button size="small" onClick={() => reconcileMut.mutate(r.receipt_id)}>
                    重匹配
                  </Button>
                ),
              },
            ] as TableColumnsType<NonNullable<HardwareReconcileDiffs['erp_only']>[number]>}
          />
        </SectionCard>
        <SectionCard title="差异清单 · 系统有 / ERP 无" description="已入账单尚未有 ERP 单核对上——提示 ERP 侧补录（财务账）。">
          <Table
            rowKey="receipt_id"
            size="middle"
            loading={diffs.isLoading}
            dataSource={diffs.data?.ocr_only ?? []}
            pagination={false}
            scroll={{ y: 240 }}
            columns={[
              { title: '单号', dataIndex: 'receipt_no', width: 170, className: 'font-mono' },
              { title: '供应商', dataIndex: 'supplier_name', ellipsis: true },
              {
                title: '到货',
                dataIndex: 'arrived_at',
                width: 110,
                render: (v) => (v ? new Date(v).toLocaleDateString('zh-CN') : '—'),
              },
            ] as TableColumnsType<NonNullable<HardwareReconcileDiffs['ocr_only']>[number]>}
          />
        </SectionCard>
      </div>
      <SectionCard
        title={`ERP 对账单（共 ${list.data?.total ?? 0} 张）`}
        action={
          <Button size="small" type={autoOnly ? 'primary' : 'default'} onClick={() => setAutoOnly((v) => !v)}>
            只看自动入账
          </Button>
        }
      >
        <QueryFilter
          common={
            <Select
              allowClear
              placeholder="匹配状态"
              style={{ width: 150 }}
              value={reconcileStatus}
              onChange={(v) => setReconcileStatus(v)}
              options={Object.entries(HARDWARE_RECONCILE_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
            />
          }
        />
        <Table
          rowKey="id"
          size="middle"
          loading={list.isLoading}
          dataSource={(list.data?.items ?? []).filter((r) => (autoOnly ? r.auto_accepted : true))}
          pagination={{ total: list.data?.total ?? 0, pageSize: 20, showTotal: (t) => `共 ${t} 张` }}
          scroll={{ x: 1000 }}
          columns={[
            { title: '单号', dataIndex: 'receipt_no', width: 170, className: 'font-mono' },
            { title: 'ERP 单号', dataIndex: 'erp_doc_no', width: 150, className: 'font-mono' },
            { title: '供应商', dataIndex: 'supplier_name', width: 160, ellipsis: true },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v) => HARDWARE_RECEIPT_STATUS_LABEL[v as HardwareReceiptStatus] ?? v,
            },
            {
              title: '匹配状态',
              dataIndex: 'reconcile_status',
              width: 110,
              render: (v: string) => (
                <StatusTag
                  tone={RECONCILE_STATUS_TONE[v] ?? 'default'}
                  label={HARDWARE_RECONCILE_STATUS_LABEL[v] ?? v}
                />
              ),
            },
            {
              title: '入账方式',
              dataIndex: 'auto_accepted',
              width: 100,
              render: (v: boolean) => (v ? <StatusTag tone="primary" label="自动" /> : <StatusTag label="人工" />),
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 115,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
            },
            {
              title: '操作',
              key: 'op',
              width: 110,
              render: (_, r) => (
                <Button size="small" onClick={() => reconcileMut.mutate(r.id)}>
                  重匹配
                </Button>
              ),
            },
          ] as TableColumnsType<HardwareReceiptRecord>}
        />
      </SectionCard>
    </div>
  )
}

function useMovementColumns(withDirection = false): TableColumnsType<HardwareMovementRecord> {
  return [
    { title: '流水号', dataIndex: 'movement_no', width: 160, className: 'font-mono' },
    {
      title: '时间',
      dataIndex: 'occurred_at',
      width: 115,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    ...(withDirection
      ? [
          {
            title: '方向',
            dataIndex: 'direction',
            width: 70,
            render: (v: string) => (
              <StatusTag
                tone={MOVEMENT_DIRECTION_TONE[v as HardwareMovementDirection] ?? 'default'}
                label={MOVEMENT_DIRECTION_LABEL[v as HardwareMovementDirection] ?? v}
              />
            ),
          },
        ]
      : []),
    {
      title: '业务',
      dataIndex: 'business_type',
      width: 90,
      render: (v: string) => HARDWARE_MOVEMENT_BIZ_LABEL[v] ?? v,
    },
    { title: '物资', dataIndex: 'material_name', width: 170, ellipsis: true },
    { title: '数量', dataIndex: 'quantity', width: 70, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
    { title: '部门', dataIndex: 'dept_name', width: 100, ellipsis: true, render: (v) => v || '—' },
    {
      title: 'ERP',
      dataIndex: 'erp_status',
      width: 80,
      render: (v: string) => (
        <StatusTag tone={ERP_STATUS_TONE[v] ?? 'warn'} label={v === 'entered' ? '已录' : '未录'} />
      ),
    },
  ]
}

export function ErpReconcilePanel() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [erpStatus, setErpStatus] = useState<string>('pending')
  const [selected, setSelected] = useState<Key[]>([])
  const { hasPermission } = usePermission()
  const canMark = hasPermission('warehouse:hardware:report:read')

  const list = useQuery({
    queryKey: ['hardware-erp-reconcile', erpStatus],
    queryFn: () =>
      fetchHardwareMovementsClient({
        direction: 'outbound',
        erp_status: erpStatus || undefined,
        pageSize: 50,
      }),
    placeholderData: keepPreviousData,
  })

  const markMut = useMutation({
    mutationFn: (ids: string[]) => markHardwareMovementsEnteredClient(ids, '仓管员'),
    onSuccess: (r) => {
      message.success(`已标记 ${r.marked} 条为「已录入ERP」`)
      setSelected([])
      qc.invalidateQueries({ queryKey: ['hardware-erp-reconcile'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <SectionCard
      title="出库侧 ERP 标记"
      description={`出库流水共 ${list.data?.total ?? 0} 条——车间在 ERP 做出库后，仓管员在此批量点「已录入」，月底对账。`}
      action={
        canMark && selected.length > 0 && (
          <Button
            type="primary"
            size="small"
            loading={markMut.isPending}
            onClick={() => markMut.mutate(selected.map(String))}
          >
            批量「已录入ERP」（{selected.length}）
          </Button>
        )
      }
    >
      <QueryFilter
        common={
          <Segmented
            value={erpStatus}
            onChange={(v) => setErpStatus(v as string)}
            options={[
              { value: 'pending', label: '未录清单' },
              { value: 'entered', label: '已录' },
              { value: '', label: '全部出库侧' },
            ]}
          />
        }
      />
      <Table
        rowKey="id"
        size="middle"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns(true)}
        rowSelection={canMark ? { selectedRowKeys: selected, onChange: setSelected } : undefined}
        locale={{ emptyText: <EmptyGuide compact title="暂无出库流水" description="车间在 ERP 做出库后，流水会出现在这里" /> }}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 850 }}
      />
    </SectionCard>
  )
}

export function DirectPanel() {
  const [dept, setDept] = useState('')
  const list = useQuery({
    queryKey: ['hardware-direct-report', dept],
    queryFn: () =>
      fetchHardwareMovementsClient({
        business_type: 'pass_out',
        dept_name: dept || undefined,
        pageSize: 50,
      }),
    placeholderData: keepPreviousData,
  })
  return (
    <SectionCard
      title="部门直发明细"
      description={`车间单独需求类直发流水（一进一出，不占库存），共 ${list.data?.total ?? 0} 条`}
      action={
        <Button
          icon={<DownloadOutlined />}
          href={hardwareMovementsExportUrl({
            business_type: 'pass_out',
            dept_name: dept || undefined,
          })}
          target="_blank"
          size="small"
        >
          导出
        </Button>
      }
    >
      <QueryFilter
        common={
          <Input
            placeholder="按部门过滤（如 发酵）"
            value={dept}
            onChange={(e) => setDept(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
        }
      />
      <Table
        rowKey="id"
        size="middle"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns()}
        locale={{ emptyText: <EmptyGuide compact title="暂无直发流水" description="车间单独需求类物资到货直领后在此留痕" /> }}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 850 }}
      />
    </SectionCard>
  )
}

export function LedgerPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canMark = hasPermission('warehouse:hardware:report:read')
  const [keyword, setKeyword] = useState('')
  const [biz, setBiz] = useState<string | undefined>(undefined)
  const [direction, setDirection] = useState<string | undefined>(undefined)
  const [erpStatus, setErpStatus] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Key[]>([])

  const list = useQuery({
    queryKey: ['hardware-ledger', keyword, biz, direction, erpStatus, page],
    queryFn: () =>
      fetchHardwareMovementsClient({
        keyword: keyword || undefined,
        business_type: biz,
        direction,
        erp_status: erpStatus,
        page,
        pageSize: 50,
      }),
    placeholderData: keepPreviousData,
  })

  const markMut = useMutation({
    mutationFn: (ids: string[]) => markHardwareMovementsEnteredClient(ids, '仓管员'),
    onSuccess: (r) => {
      message.success(`已标记 ${r.marked} 条为 ERP 已录`)
      setSelected([])
      queryClient.invalidateQueries({ queryKey: ['hardware-ledger'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  return (
    <SectionCard
      title="出入库流水台账"
      action={
        <>
          {canMark && selected.length > 0 && (
            <Button size="small" loading={markMut.isPending} onClick={() => markMut.mutate(selected.map(String))}>
              标记选中为 ERP 已录（{selected.length}）
            </Button>
          )}
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            href={hardwareMovementsExportUrl({
              keyword: keyword || undefined,
              business_type: biz,
              direction,
              erp_status: erpStatus,
            })}
            target="_blank"
          >
            导出台账 Excel
          </Button>
        </>
      }
    >
      <QueryFilter
        common={
          <>
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: '#999' }} />}
              placeholder="流水号 / 品名 / 批次"
              style={{ width: 220 }}
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value)
                setPage(1)
              }}
            />
            <Segmented
              value={direction ?? 'all'}
              onChange={(v) => {
                setDirection(v === 'all' ? undefined : (v as string))
                setPage(1)
              }}
              options={[
                { value: 'all', label: '全部' },
                { value: 'inbound', label: '入' },
                { value: 'outbound', label: '出' },
              ]}
            />
            <Segmented
              value={erpStatus ?? 'all'}
              onChange={(v) => {
                setErpStatus(v === 'all' ? undefined : (v as string))
                setPage(1)
              }}
              options={[
                { value: 'all', label: 'ERP全部' },
                { value: 'pending', label: '未录' },
                { value: 'entered', label: '已录' },
              ]}
            />
            <Select
              allowClear
              placeholder="业务类型"
              style={{ width: 140 }}
              value={biz}
              onChange={(v) => {
                setBiz(v)
                setPage(1)
              }}
              options={Object.entries(HARDWARE_MOVEMENT_BIZ_LABEL).map(([v, l]) => ({ value: v, label: l }))}
            />
          </>
        }
      />
      <Table
        rowKey="id"
        size="middle"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns(true)}
        rowSelection={canMark ? { selectedRowKeys: selected, onChange: setSelected } : undefined}
        locale={{ emptyText: <EmptyGuide compact title="暂无流水记录" description="调整筛选条件或先完成出入库操作" /> }}
        pagination={{
          current: page,
          pageSize: 50,
          total: list.data?.total ?? 0,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
        scroll={{ x: 870 }}
      />
    </SectionCard>
  )
}
