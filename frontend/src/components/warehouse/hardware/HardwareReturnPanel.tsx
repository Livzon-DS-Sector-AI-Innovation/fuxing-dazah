'use client'

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
} from 'antd'
import type { TableColumnsType } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  acceptHardwareReturnClient,
  approveHardwareReturnClient,
  cancelHardwareReturnClient,
  createHardwareReturnClient,
  fetchHardwareMaterialsClient,
  fetchHardwareReturnsClient,
  fetchHardwareStockDetailClient,
  rejectHardwareReturnClient,
  signHardwareReturnClient,
  submitHardwareReturnClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_RETURN_STATUS_LABEL,
  type HardwareReturnRecord,
  type HardwareReturnStatus,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { EmptyGuide, QueryFilter, SectionCard, StatusTag } from '@/components/warehouse'
import { RETURN_STATUS_TONE } from './constants'
import { formatQty } from './format'

interface ReturnLine {
  material_id: string
  quantity: number
  preferred_lot_id?: string
}

/**
 * 退料页签（2026-11-26 双链路）：
 * - 平台发起（从已发料领料单）：待审批 → 审批人通过（飞书/平台）→ 待验收 →
 *   仓管「验收回加」物料回库存；驳回/撤回留证。
 * - 老登记/飞书自建（channel 空）：待提交=待签收验收，签收→验收回加，原行为不变。
 */
export function HardwareReturnPanel() {
  const { message, modal } = App.useApp()
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

  // 退料状态会影响库存（验收回加）与申请单据额度，统一按前缀失效
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hardware-returns'] })
    qc.invalidateQueries({ queryKey: ['warehouse', 'hardware'] })
  }

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

  const submitMut = useMutation({
    mutationFn: (id: string) => submitHardwareReturnClient(id),
    onSuccess: (r) => {
      message.success(
        r.approval_channel === 'feishu'
          ? '已提交，飞书审批单已发给所选审批人'
          : '已提交（待审批），等审批人点通过',
      )
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const approveMut = useMutation({
    mutationFn: (id: string) => approveHardwareReturnClient(id),
    onSuccess: () => {
      message.success('已审批通过（待仓管验收回加）')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const acceptMut = useMutation({
    mutationFn: (id: string) => acceptHardwareReturnClient(id, 'web'),
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
      message.success('已驳回（留证不动账）')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelHardwareReturnClient(id),
    onSuccess: () => {
      message.success('已撤回')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const askReject = (r: HardwareReturnRecord) => {
    let reason = ''
    modal.warning({
      title: r.status === 'pending' ? '驳回报废审批' : '拒退（实物不符留证）',
      content: (
        <Input.TextArea
          rows={3}
          placeholder={r.status === 'pending' ? '驳回原因' : '不合格说明（留证）'}
          onChange={(e) => {
            reason = e.target.value
          }}
        />
      ),
      okText: '确认驳回',
      okButtonProps: { danger: true },
      onOk: () =>
        rejectMut.mutate({
          id: r.id,
          reason: reason.trim() || (r.status === 'pending' ? '未填写原因' : '质量不合格'),
        }),
    })
  }

  const actionsFor = (r: HardwareReturnRecord) => {
    const isPlatform = !!r.approval_channel
    if (!canManage && !(isPlatform && r.status === 'pending' && r.can_approve)) {
      return (
        <span className="text-xs text-gray-400">
          {r.status === 'accepted' && r.accepted_by ? `验收 ${r.accepted_by}` : ''}
          {r.status === 'rejected' ? r.rejected_reason : ''}
        </span>
      )
    }
    // 平台发起链路
    if (isPlatform) {
      return (
        <Space size={4} wrap>
          {r.status === 'draft' && (
            <Button size="small" type="primary" onClick={() => submitMut.mutate(r.id)}>
              提交审批
            </Button>
          )}
          {r.status === 'pending' && r.can_approve && (
            <>
              <Button size="small" type="primary" onClick={() => approveMut.mutate(r.id)}>
                通过
              </Button>
              <Button size="small" danger onClick={() => askReject(r)}>
                驳回
              </Button>
            </>
          )}
          {r.status === 'approved' && canManage && (
            <>
              <Popconfirm
                title="验收后批次回加库存，确认？"
                onConfirm={() => acceptMut.mutate(r.id)}
              >
                <Button size="small" type="primary">
                  验收回加
                </Button>
              </Popconfirm>
              <Button size="small" danger onClick={() => askReject(r)}>
                拒退
              </Button>
            </>
          )}
          {(r.status === 'draft' || r.status === 'pending') && canManage && (
            <Button size="small" onClick={() => cancelMut.mutate(r.id)}>
              撤回
            </Button>
          )}
        </Space>
      )
    }
    // 老登记/飞书自建链路（原行为不变）
    if (r.status === 'draft') {
      return (
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
              <Button size="small" danger type="link" onClick={() => askReject(r)}>
                拒退
              </Button>
            </>
          )}
        </Space>
      )
    }
    return (
      <span className="text-xs text-gray-400">
        {r.status === 'accepted' && r.accepted_by ? `验收 ${r.accepted_by}` : ''}
        {r.status === 'rejected' ? r.rejected_reason : ''}
      </span>
    )
  }

  const columns: TableColumnsType<HardwareReturnRecord> = [
    { title: '退库单号', dataIndex: 'return_no', width: 165, className: 'font-mono' },
    { title: '退库部门', dataIndex: 'dept_name', width: 100 },
    { title: '退库人', dataIndex: 'returned_by', width: 84 },
    {
      title: '明细',
      width: 200,
      render: (_, r) => (
        <div className="text-xs">
          {r.items.map((i, idx) => (
            <div key={idx}>
              {i.name} × <span className="tabular-nums">{formatQty(i.quantity)}</span>
              {i.unit || ''}
            </div>
          ))}
        </div>
      ),
    },
    {
      title: '审批人',
      dataIndex: 'approver_name',
      width: 84,
      render: (v: string | null, r) => v || (r.approval_channel ? '—' : '（登记）'),
    },
    {
      title: '签收',
      dataIndex: 'leader_signed',
      width: 84,
      render: (v: boolean, r) =>
        v ? (
          <StatusTag tone="ok" label={r.leader_signed_by || '已签'} />
        ) : (
          <StatusTag label="未签" />
        ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 84,
      render: (v: HardwareReturnStatus) => (
        <StatusTag tone={RETURN_STATUS_TONE[v] ?? 'default'} label={HARDWARE_RETURN_STATUS_LABEL[v]} />
      ),
    },
    {
      title: '操作',
      width: 250,
      render: (_, r) => actionsFor(r),
    },
  ]

  return (
    <SectionCard
      title="退库单"
      description="从「出库 → 已发料」发起退料走审批（审批人同意后仓管验收回加）；「登记退库」为无审批直录链路。"
      action={
        canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            登记退库
          </Button>
        )
      }
    >
      <QueryFilter
        common={
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={status}
            onChange={setStatus}
            options={Object.entries(HARDWARE_RETURN_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
          />
        }
      />
      <Table
        rowKey="id"
        size="middle"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={columns}
        locale={{ emptyText: <EmptyGuide compact title="暂无退库单" description="在「出库 → 已发料」的领料单上点「退料」发起审批退料" /> }}
        pagination={{ total: list.data?.total ?? 0, pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 1050 }}
      />

      <ReturnCreateModal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onSubmit={(v) => createMut.mutate(v)}
        loading={createMut.isPending}
      />
    </SectionCard>
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
        min={1}
        precision={0}
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
            { title: '余额', dataIndex: 'remaining_quantity', width: 80, render: (v: unknown) => formatQty(v) },
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
