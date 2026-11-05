'use client'

// 五金库报表（二期 M6）：ERP 对账（出库侧 erp_status 批量标记+月底未录清单）/
// 部门 direct 直发明细 / 全量流水台账导出。设计 §十一 二期。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type Key } from 'react'
import {
  App,
  Button,
  Input,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import {
  fetchHardwareMovementsClient,
  hardwareMovementsExportUrl,
  markHardwareMovementsEnteredClient,
} from '@/lib/api/warehouse-hardware'
import { HARDWARE_MOVEMENT_BIZ_LABEL, type HardwareMovementRecord } from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { PageHeader } from '@/components/warehouse'

type TabKey = 'erp' | 'direct' | 'ledger'

export function HardwareReportsBoard() {
  const [tab, setTab] = useState<TabKey>('erp')
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumb={['仓储管理', '五金库', '台账报表']}
        title="五金库台账报表"
        description="ERP 对账（出库侧标记+月底未录清单）· 部门直发明细 · 全量流水台账导出"
      />
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as TabKey)}
        options={[
          { value: 'erp', label: 'ERP 对账' },
          { value: 'direct', label: '部门直发明细' },
          { value: 'ledger', label: '流水台账' },
        ]}
      />
      {tab === 'erp' && <ErpReconcilePanel />}
      {tab === 'direct' && <DirectPanel />}
      {tab === 'ledger' && <LedgerPanel />}
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

function ErpReconcilePanel() {
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

function DirectPanel() {
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

function LedgerPanel() {
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
