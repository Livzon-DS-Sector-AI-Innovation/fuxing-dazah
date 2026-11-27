'use client'

import { useQuery } from '@tanstack/react-query'
import { App, Input, InputNumber, Modal, Select, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import { useState } from 'react'

import {
  createReturnFromRequisitionClient,
  fetchReturnApproversClient,
  fetchReturnableQtyClient,
} from '@/lib/api/warehouse-hardware'
import type {
  HardwareRequisitionRecord,
  HardwareReturnableRow,
} from '@/types/warehouse-hardware'
import { formatQty } from './format'

/**
 * 从已发料领料单发起退料（2026-11-26）：确定即创建并提交审批（同申领口径）。
 * 额度逐行上限=可退量（实发−已退/在退，后端双卡点）；批次预填发料批次
 * （fifo_lot_allocations 首批）；审批人主管及以上必选，提交后飞书审批单发给
 * 所选审批人（未配置分支=平台点通过），同意后仓管验收回加。
 */
export function ReturnCreateModal({
  requisition,
  onClose,
  onDone,
}: {
  requisition: HardwareRequisitionRecord | null
  onClose: () => void
  onDone: () => void
}) {
  const { message, modal } = App.useApp()
  const [saving, setSaving] = useState(false)
  const [approverId, setApproverId] = useState<string | undefined>(undefined)
  const [approverKeyword, setApproverKeyword] = useState('')
  const [reasonNote, setReasonNote] = useState('')
  // 用户改过的行内退料量：material_id → 量（未改的行渲染期回退满额可退，
  // 避免 effect 同步 setState 的级联渲染）
  const [overrides, setOverrides] = useState<Record<string, number>>({})

  // 额度（打开时按领料单拉）
  const { data: quota, isFetching: quotaLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'returnable', requisition?.id],
    queryFn: () => fetchReturnableQtyClient(requisition!.id),
    enabled: !!requisition,
  })
  // 审批人下拉（与申领同池：主管及以上）
  const { data: approvers = [], isFetching: approversLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'return-approvers', approverKeyword],
    queryFn: () =>
      fetchReturnApproversClient({ keyword: approverKeyword || undefined, limit: 50 }),
    enabled: !!requisition,
    staleTime: 60_000,
  })
  const approverOptions = approvers.map((a) => ({
    value: a.user_id,
    label: `${a.supervisor ? '【主管及以上】' : ''}${a.name}（${a.department || '未匹配部门'} · ${a.position || '—'}）`,
  }))
  const selectedApprover = approvers.find((a) => a.user_id === approverId) ?? null

  if (!requisition) return null

  const rows: Array<HardwareReturnableRow & { preferred_lot_id?: string | null }> = (
    quota?.items ?? []
  ).map((q) => {
    // 发料批次预填：领料明细的 fifo_lot_allocations 首批（回原批次）
    const reqItem = requisition.items.find((i) => i.material_id === q.material_id)
    const firstLot = reqItem?.fifo_lot_allocations?.find((l) => l.lot_id)
    return { ...q, preferred_lot_id: firstLot?.lot_id ?? null }
  })

  // 渲染期派生：有效退料量 = 用户改过的值 ?? 该行满额可退（可退 0 → 0）
  const quantities: Record<string, number> = Object.fromEntries(
    rows.map((r) => [r.material_id, overrides[r.material_id] ?? Math.max(r.returnable, 0)]),
  )

  const submitConfirmed = async () => {
    if (!requisition) return
    setSaving(true)
    try {
      const items = Object.entries(quantities)
        .filter(([, qty]) => qty > 0)
        .map(([material_id, qty]) => {
          const row = rows.find((r) => r.material_id === material_id)
          return {
            material_id,
            quantity: qty,
            ...(row?.preferred_lot_id ? { preferred_lot_id: row.preferred_lot_id } : {}),
          }
        })
      if (!items.length) {
        message.warning('请至少填写一行退料数量')
        return
      }
      const created = await createReturnFromRequisitionClient({
        requisition_id: requisition.id,
        approver_user_id: selectedApprover?.user_id,
        approver_name: selectedApprover?.name,
        reason_note: reasonNote || undefined,
        items,
      })
      message.success(
        created.approval_channel === 'feishu'
          ? '退料单已提交，飞书审批单已发给所选审批人；同意后由仓管验收回加'
          : '退料单已提交（待审批），等审批人在「退料」页签点通过',
      )
      setOverrides({})
      setApproverId(undefined)
      setReasonNote('')
      onDone()
      onClose()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '退料单提交失败')
    } finally {
      setSaving(false)
    }
  }

  const onOk = async () => {
    const hasQty = Object.values(quantities).some((q) => q > 0)
    if (!hasQty) {
      message.error('请至少填写一行退料数量（可退量为 0 的物资不能退）')
      return
    }
    if (!selectedApprover) {
      message.error('请选择审批人（主管及以上）后再提交')
      return
    }
    const detail = Object.entries(quantities)
      .filter(([, qty]) => qty > 0)
      .map(([mid, qty]) => {
        const row = rows.find((r) => r.material_id === mid)
        return `${row?.name ?? mid} × ${formatQty(qty)}${row?.unit ?? ''}`
      })
      .join('；')
    modal.confirm({
      title: '确认发起退料',
      width: 460,
      okText: '确认提交',
      cancelText: '再改改',
      content: (
        <div className="space-y-1 text-[13px]">
          <div>原领料单：{requisition.req_no}</div>
          <div className="text-[12px] text-gray-600">退料：{detail}</div>
          <div>审批人：{selectedApprover?.name ?? '-'}</div>
          <div className="pt-1 text-[12px] text-gray-500">
            提交后即占用可退额度；审批人通过（飞书或平台）后进待验收，仓管验收回加后物料回库存。
          </div>
        </div>
      ),
      onOk: () => submitConfirmed(),
    })
  }

  const columns: TableColumnsType<typeof rows[number]> = [
    { title: '物资', dataIndex: 'name', width: 170, ellipsis: true },
    { title: '规格', dataIndex: 'spec', width: 120, ellipsis: true, render: (v) => v || '-' },
    { title: '单位', dataIndex: 'unit', width: 56 },
    {
      title: '实发',
      dataIndex: 'issued',
      width: 76,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) => formatQty(v),
    },
    {
      title: '已退/在退',
      dataIndex: 'returned',
      width: 88,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) => formatQty(v),
    },
    {
      title: '可退',
      dataIndex: 'returnable',
      width: 76,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) => formatQty(v),
    },
    {
      title: '本次退料',
      width: 120,
      render: (_: unknown, r) => (
        <InputNumber
          size="small"
          min={0}
          precision={3}
          max={r.returnable}
          value={quantities[r.material_id] ?? 0}
          disabled={r.returnable <= 0}
          onChange={(v) =>
            setOverrides((prev) => ({ ...prev, [r.material_id]: Number(v) || 0 }))
          }
          style={{ width: '100%' }}
        />
      ),
    },
  ]

  return (
    <Modal
      title={`发起退料 · ${requisition.req_no}`}
      open={!!requisition}
      onCancel={onClose}
      onOk={onOk}
      confirmLoading={saving}
      okText="提交退料"
      width={760}
      destroyOnHidden
    >
      <div className="mb-3 rounded bg-gray-50 px-3 py-2 text-[13px] leading-6">
        <div>
          部门：{requisition.dept_name}　领用人：{requisition.applicant}　状态：已发料
        </div>
        <div className="text-[12px] text-gray-500">
          退料数不能超过该单可退量（实发 − 已退/在退）；提交即发起审批，审批人同意后由仓管验收回加。
        </div>
      </div>
      <Table
        size="small"
        rowKey="material_id"
        columns={columns}
        dataSource={rows}
        pagination={false}
        loading={quotaLoading && !quota}
        locale={{ emptyText: '该领料单没有可退物资' }}
      />
      <div className="mt-3 space-y-3">
        <div>
          <div className="mb-1 text-[13px] font-medium">审批人（主管及以上）<span className="text-red-500"> *</span></div>
          <Select
            showSearch
            filterOption={false}
            onSearch={setApproverKeyword}
            onChange={(v) => setApproverId(v)}
            value={approverId}
            placeholder="搜索姓名 / 部门 / 职位选择审批人"
            options={approverOptions}
            notFoundContent={approversLoading ? '搜索中…' : '无匹配审批人（主管及以上）'}
            allowClear
            style={{ width: '100%' }}
          />
        </div>
        <div>
          <div className="mb-1 text-[13px] font-medium">退料说明</div>
          <Input.TextArea
            rows={2}
            value={reasonNote}
            onChange={(e) => setReasonNote(e.target.value)}
            placeholder="如：用剩退回 / 规格不符换货退回"
            maxLength={500}
            showCount
          />
        </div>
      </div>
    </Modal>
  )
}
