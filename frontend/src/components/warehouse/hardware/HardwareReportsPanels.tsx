'use client'

// 五金库台账面板组（原二期 M6「五金台账报表」页拆面板化，2026-11-06 并入「盘点与台账」页）：
// ERP 入库对账（erp_import 匹配+差异清单两栏）/ ERP 出库侧标记 / 部门 direct 直发明细 /
// 全量流水台账导出。报废面板在 HardwareScrapPanel.tsx。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type Key } from 'react'
import {
  App,
  Button,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
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
  type HardwareMovementRecord,
  type HardwareReceiptRecord,
  type HardwareReceiptStatus,
  type HardwareReconcileDiffs,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'

// ── ERP 入库对账（三期 M8）：erp_import 单列表+匹配状态+差异清单两栏+自动入账筛选 ──

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

  const reconcileColor: Record<string, string> = {
    none: 'default',
    unmatched: 'red',
    matched: 'blue',
    verified: 'green',
    discrepancy: 'orange',
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded border p-3">
          <Typography.Text strong>差异清单 · ERP 有 / OCR 无</Typography.Text>
          <Typography.Paragraph type="secondary" className="!mb-2 text-xs">
            erp_import 单未匹配到既有 OCR 入库单——可人工确认入账（补录兜底，生成批次占库存）。
          </Typography.Paragraph>
          <Table
            rowKey="receipt_id"
            size="small"
            loading={diffs.isLoading}
            dataSource={diffs.data?.erp_only ?? []}
            pagination={false}
            scroll={{ y: 240 }}
            columns={[
              { title: '单号', dataIndex: 'receipt_no', width: 170 },
              { title: 'ERP 单号', dataIndex: 'erp_doc_no', width: 140 },
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
        </div>
        <div className="rounded border p-3">
          <Typography.Text strong>差异清单 · OCR 有 / ERP 无</Typography.Text>
          <Typography.Paragraph type="secondary" className="!mb-2 text-xs">
            已入账 OCR/manual 单尚未有 ERP 单核对上——提示 ERP 侧补录（财务账）。
          </Typography.Paragraph>
          <Table
            rowKey="receipt_id"
            size="small"
            loading={diffs.isLoading}
            dataSource={diffs.data?.ocr_only ?? []}
            pagination={false}
            scroll={{ y: 240 }}
            columns={[
              { title: '单号', dataIndex: 'receipt_no', width: 170 },
              { title: '供应商', dataIndex: 'supplier_name', ellipsis: true },
              {
                title: '到货',
                dataIndex: 'arrived_at',
                width: 110,
                render: (v) => (v ? new Date(v).toLocaleDateString('zh-CN') : '—'),
              },
            ] as TableColumnsType<NonNullable<HardwareReconcileDiffs['ocr_only']>[number]>}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Space wrap>
          <Select
            allowClear
            placeholder="匹配状态"
            style={{ width: 150 }}
            value={reconcileStatus}
            onChange={(v) => setReconcileStatus(v)}
            options={Object.entries(HARDWARE_RECONCILE_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
          />
          <Button size="small" type={autoOnly ? 'primary' : 'default'} onClick={() => setAutoOnly((v) => !v)}>
            只看自动入账（M9 复核抽检）
          </Button>
          <Typography.Text type="secondary">
            erp_import 单共 {list.data?.total ?? 0} 张——匹配成功双向核对通过（verified 不再入账，防双计）。
          </Typography.Text>
        </Space>
        <Table
          rowKey="id"
          size="small"
          loading={list.isLoading}
          dataSource={(list.data?.items ?? []).filter((r) => (autoOnly ? r.auto_accepted : true))}
          pagination={{ total: list.data?.total ?? 0, pageSize: 20, showTotal: (t) => `共 ${t} 张` }}
          scroll={{ x: 1000 }}
          columns={[
            { title: '单号', dataIndex: 'receipt_no', width: 170 },
            { title: 'ERP 单号', dataIndex: 'erp_doc_no', width: 150 },
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
                <Tag color={reconcileColor[v] ?? 'default'}>
                  {HARDWARE_RECONCILE_STATUS_LABEL[v] ?? v}
                </Tag>
              ),
            },
            {
              title: '自动入账',
              dataIndex: 'auto_accepted',
              width: 100,
              render: (v: boolean) =>
                v ? <Tag color="purple">⚙️ 自动</Tag> : <Tag>人工</Tag>,
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 150,
              render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
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
      </div>
    </div>
  )
}

function useMovementColumns() {
  return [
    { title: '流水号', dataIndex: 'movement_no', width: 180 },
    {
      title: '时间',
      dataIndex: 'occurred_at',
      width: 150,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    {
      title: '业务',
      dataIndex: 'business_type',
      width: 90,
      render: (v: string) => HARDWARE_MOVEMENT_BIZ_LABEL[v] ?? v,
    },
    { title: '物资', dataIndex: 'material_name', width: 170, ellipsis: true },
    { title: '数量', dataIndex: 'quantity', width: 80 },
    { title: '部门', dataIndex: 'dept_name', width: 100, render: (v) => v || '—' },
    {
      title: 'ERP',
      dataIndex: 'erp_status',
      width: 80,
      render: (v: string) => (v === 'entered' ? <Tag color="green">已录</Tag> : <Tag color="red">未录</Tag>),
    },
  ] as TableColumnsType<HardwareMovementRecord>
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
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Select
          value={erpStatus}
          style={{ width: 130 }}
          onChange={(v) => setErpStatus(v)}
          options={[
            { value: 'pending', label: '未录清单' },
            { value: 'entered', label: '已录' },
            { value: '', label: '全部出库侧' },
          ]}
        />
        <span className="text-gray-500">
          出库侧流水共 {list.data?.total ?? 0} 条——车间在 ERP 做出库后，仓管员在此批量点「已录入」，月底对账。
        </span>
        {canMark && selected.length > 0 && (
          <Button
            type="primary"
            size="small"
            loading={markMut.isPending}
            onClick={() => markMut.mutate(selected.map(String))}
          >
            批量「已录入ERP」（{selected.length}）
          </Button>
        )}
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns()}
        rowSelection={canMark ? { selectedRowKeys: selected, onChange: setSelected } : undefined}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
      />
    </div>
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
    <div className="space-y-3">
      <Space wrap>
        <Input
          placeholder="按部门过滤（如 发酵）"
          value={dept}
          onChange={(e) => setDept(e.target.value)}
          style={{ width: 200 }}
          allowClear
        />
        <span className="text-sm text-gray-500">
          direct 车间单独需求类直发流水（一进一出，净零不占库存），共 {list.data?.total ?? 0} 条
        </span>
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
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns()}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
      />
    </div>
  )
}

export function LedgerPanel() {
  const [keyword, setKeyword] = useState('')
  const [biz, setBiz] = useState<string | undefined>(undefined)
  const list = useQuery({
    queryKey: ['hardware-ledger', keyword, biz],
    queryFn: () =>
      fetchHardwareMovementsClient({ keyword: keyword || undefined, business_type: biz, pageSize: 50 }),
    placeholderData: keepPreviousData,
  })
  return (
    <div className="space-y-3">
      <Space wrap>
        <Input.Search
          placeholder="搜流水号/品名/批次"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 220 }}
          allowClear
        />
        <Select
          allowClear
          placeholder="业务类型"
          style={{ width: 130 }}
          value={biz}
          onChange={(v) => setBiz(v)}
          options={Object.entries(HARDWARE_MOVEMENT_BIZ_LABEL).map(([v, l]) => ({ value: v, label: l }))}
        />
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          href={hardwareMovementsExportUrl({
            keyword: keyword || undefined,
            business_type: biz,
          })}
          target="_blank"
        >
          导出台账 Excel（5000 行封顶）
        </Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={useMovementColumns()}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
      />
    </div>
  )
}
