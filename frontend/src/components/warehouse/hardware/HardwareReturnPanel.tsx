'use client'

// 五金库退库面板（二期 M4）：退库单登记 → 部门负责人签收 → 仓管员验收
// （批次回加：原 lot 优先，无则新建 return 批次）/ 不合格拒退。
// 挂出入库工作台「退库」Tab。设计 §2.6。

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
import { PlusOutlined } from '@ant-design/icons'
import {
  acceptHardwareReturnClient,
  createHardwareReturnClient,
  fetchHardwareMaterialsClient,
  fetchHardwareReturnsClient,
  fetchHardwareStockDetailClient,
  rejectHardwareReturnClient,
  signHardwareReturnClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_RETURN_STATUS_LABEL,
  type HardwareReturnRecord,
  type HardwareReturnStatus,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'

const STATUS_COLOR: Record<HardwareReturnStatus, string> = {
  draft: 'processing',
  accepted: 'success',
  rejected: 'error',
}

interface ReturnLine {
  material_id: string
  quantity: number
  preferred_lot_id?: string
}

export function HardwareReturnPanel() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [createOpen, setCreateOpen] = useState(false)
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:return:manage')

  const list = useQuery({
    queryKey: ['hardware-returns', status],
    queryFn: () => fetchHardwareReturnsClient({ status, pageSize: 50 }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['hardware-returns'] })

  const createMut = useMutation({
    mutationFn: (v: {
      dept_name: string
      returned_by: string
      remark?: string
      items: ReturnLine[]
    }) => createHardwareReturnClient(v),
    onSuccess: (ret) => {
      message.success(`退库单 ${ret.return_no} 已登记，待部门负责人签收`)
      setCreateOpen(false)
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const signMut = useMutation({
    mutationFn: (v: { id: string; leader: string }) =>
      signHardwareReturnClient(v.id, v.leader),
    onSuccess: () => {
      message.success('负责人已签收')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const acceptMut = useMutation({
    mutationFn: (id: string) => acceptHardwareReturnClient(id, '仓管员'),
    onSuccess: (ret) => {
      const lines = (ret.lot_adjustments ?? [])
        .map((a) => `${a.material}→${a.lot_no}（${a.mode === 'preferred' ? '回原批次' : '新建批次'}）`)
        .join('；')
      message.success(`验收完成，批次已回加：${lines}`)
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const rejectMut = useMutation({
    mutationFn: (v: { id: string; reason: string }) => rejectHardwareReturnClient(v.id, v.reason),
    onSuccess: () => {
      message.success('已拒退（留证不动账）')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: TableColumnsType<HardwareReturnRecord> = [
    { title: '退库单号', dataIndex: 'return_no', width: 165 },
    { title: '退库部门', dataIndex: 'dept_name', width: 110 },
    { title: '退库人', dataIndex: 'returned_by', width: 90 },
    {
      title: '明细',
      width: 220,
      render: (_, r) => (
        <div className="text-xs">
          {r.items.map((i, idx) => (
            <div key={idx}>
              {i.name} × {i.quantity}
              {i.unit || ''}
            </div>
          ))}
        </div>
      ),
    },
    {
      title: '负责人签',
      dataIndex: 'leader_signed',
      width: 90,
      render: (v: boolean, r) =>
        v ? (
          <Tag color="green">{r.leader_signed_by || '已签'}</Tag>
        ) : (
          <Tag>未签</Tag>
        ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: HardwareReturnStatus) => (
        <Tag color={STATUS_COLOR[v]}>{HARDWARE_RETURN_STATUS_LABEL[v]}</Tag>
      ),
    },
    {
      title: '操作',
      width: 260,
      render: (_, r) =>
        canManage && r.status === 'draft' ? (
          <Space size={4} wrap>
            {!r.leader_signed && (
              <Popconfirm
                title="以部门负责人身份签收？"
                onConfirm={() => signMut.mutate({ id: r.id, leader: '部门负责人' })}
              >
                <Button size="small" type="link">
                  负责人签收
                </Button>
              </Popconfirm>
            )}
            {r.leader_signed && (
              <>
                <Popconfirm title="验收后批次回加库存，确认？" onConfirm={() => acceptMut.mutate(r.id)}>
                  <Button size="small" type="primary">
                    验收回加
                  </Button>
                </Popconfirm>
                <Popconfirm
                  title="拒退原因"
                  description={
                    <Input id={`reject-reason-${r.id}`} placeholder="不合格说明（留证）" />
                  }
                  onConfirm={() => {
                    const el = document.getElementById(`reject-reason-${r.id}`) as HTMLInputElement
                    rejectMut.mutate({ id: r.id, reason: el?.value || '质量不合格' })
                  }}
                >
                  <Button size="small" danger type="link">
                    拒退
                  </Button>
                </Popconfirm>
              </>
            )}
          </Space>
        ) : (
          <span className="text-xs text-gray-400">
            {r.status === 'accepted' && r.accepted_by ? `验收 ${r.accepted_by}` : ''}
            {r.status === 'rejected' ? r.rejected_reason : ''}
          </span>
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 120 }}
          value={status}
          onChange={setStatus}
          options={Object.entries(HARDWARE_RETURN_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            登记退库
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
        scroll={{ x: 950 }}
      />

      <ReturnCreateModal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onSubmit={(v) => createMut.mutate(v)}
        loading={createMut.isPending}
      />
    </div>
  )
}

function ReturnCreateModal({
  open,
  onCancel,
  onSubmit,
  loading,
}: {
  open: boolean
  onCancel: () => void
  onSubmit: (v: { dept_name: string; returned_by: string; remark?: string; items: ReturnLine[] }) => void
  loading: boolean
}) {
  const [lines, setLines] = useState<ReturnLine[]>([{ material_id: '', quantity: 1 }])
  const [dept, setDept] = useState('')
  const [person, setPerson] = useState('')
  const [remark, setRemark] = useState('')

  const materials = useQuery({
    queryKey: ['hardware-return-materials'],
    queryFn: () => fetchHardwareMaterialsClient('', 200),
    enabled: open,
  })

  const valid = dept.trim() && person.trim() && lines.every((l) => l.material_id && l.quantity > 0)

  return (
    <Modal
      title="登记退库单（仅共用类，验收后批次回加）"
      open={open}
      onCancel={onCancel}
      confirmLoading={loading}
      okButtonProps={{ disabled: !valid }}
      onOk={() =>
        onSubmit({
          dept_name: dept.trim(),
          returned_by: person.trim(),
          remark: remark.trim() || undefined,
          items: lines,
        })
      }
      okText="登记"
      width={560}
    >
      <Space direction="vertical" className="w-full" size={8}>
        <Space wrap>
          <Input
            placeholder="退库部门（如 发酵）"
            value={dept}
            onChange={(e) => setDept(e.target.value)}
            style={{ width: 180 }}
          />
          <Input
            placeholder="退库人"
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            style={{ width: 140 }}
          />
        </Space>
        {lines.map((line, idx) => (
          <ReturnLineEditor
            key={idx}
            line={line}
            materialOptions={(materials.data?.items ?? []).map((m) => ({
              value: m.id,
              label: `${m.name}（${m.spec || '无规格'}）`,
            }))}
            onChange={(next) => setLines(lines.map((l, i) => (i === idx ? next : l)))}
            onRemove={idx > 0 ? () => setLines(lines.filter((_, i) => i !== idx)) : undefined}
          />
        ))}
        <Button
          size="small"
          onClick={() => setLines([...lines, { material_id: '', quantity: 1 }])}
        >
          + 加一行
        </Button>
        <Input.TextArea
          rows={2}
          placeholder="备注（选填）"
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
        />
        <div className="text-xs text-gray-400">
          批次留空=系统自动回原批次优先；退库需部门负责人签收后仓管员才能验收。
        </div>
      </Space>
    </Modal>
  )
}

function ReturnLineEditor({
  line,
  materialOptions,
  onChange,
  onRemove,
}: {
  line: ReturnLine
  materialOptions: Array<{ value: string; label: string }>
  onChange: (next: ReturnLine) => void
  onRemove?: () => void
}) {
  const { message } = App.useApp()
  const [lotDrawerFor, setLotDrawerFor] = useState<string | null>(null)

  const lots = useQuery({
    queryKey: ['hardware-return-lots', lotDrawerFor],
    queryFn: () => fetchHardwareStockDetailClient(lotDrawerFor!),
    enabled: !!lotDrawerFor,
  })

  return (
    <Space wrap align="center">
      <Select
        showSearch
        optionFilterProp="label"
        placeholder="选择物料（共用类）"
        style={{ width: 260 }}
        value={line.material_id || undefined}
        options={materialOptions}
        onChange={(v) => onChange({ ...line, material_id: v, preferred_lot_id: undefined })}
      />
      <InputNumber
        min={0.001}
        value={line.quantity}
        onChange={(v) => onChange({ ...line, quantity: v ?? 0 })}
        style={{ width: 100 }}
        addonAfter="数量"
      />
      <Button
        size="small"
        disabled={!line.material_id}
        onClick={() => setLotDrawerFor(line.material_id)}
      >
        选批次{line.preferred_lot_id ? '✓' : ''}
      </Button>
      {onRemove && (
        <Button size="small" type="link" danger onClick={onRemove}>
          删行
        </Button>
      )}

      <Drawer
        title="选择优先回加批次（可跳过=自动回原批次）"
        open={!!lotDrawerFor}
        onClose={() => setLotDrawerFor(null)}
        width={380}
      >
        <Table
          rowKey="lot_id"
          size="small"
          loading={lots.isLoading}
          dataSource={lots.data?.lots ?? []}
          pagination={false}
          columns={[
            { title: '批次', dataIndex: 'lot_no', width: 120 },
            { title: '余额', dataIndex: 'remaining_quantity', width: 80 },
            {
              title: '',
              width: 70,
              render: (_, r: { lot_id: string }) => (
                <Button
                  size="small"
                  type="link"
                  onClick={() => {
                    onChange({ ...line, preferred_lot_id: r.lot_id })
                    setLotDrawerFor(null)
                    message.success('已选批次')
                  }}
                >
                  选它
                </Button>
              ),
            },
          ]}
        />
      </Drawer>
    </Space>
  )
}
