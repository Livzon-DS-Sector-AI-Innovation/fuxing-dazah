'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'
import {
  createHardwareScrapClient,
  fetchHardwareMaterialsClient,
  fetchHardwareScrapsClient,
  fetchScrapApproversClient,
  submitHardwareScrapClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_SCRAP_REASON_LABEL,
  HARDWARE_SCRAP_STATUS_LABEL,
  type HardwareScrapRecord,
  type HardwareScrapReason,
  type HardwareScrapStatus,
} from '@/types/warehouse-hardware'
import { EmptyGuide, QueryFilter, SectionCard, StatusTag } from '@/components/warehouse'
import { SCRAP_STATUS_TONE } from './constants'
import { useScrapActions } from './useScrapActions'
import { ScrapRowActions } from './ScrapRowActions'
import { ScrapDetailDrawer } from './ScrapDetailDrawer'
import { ScrapExecuteModal } from './ScrapExecuteModal'

export function HardwareScrapPanel() {
  const scrapActions = useScrapActions()
  const { canManage } = scrapActions
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [executingId, setExecutingId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const list = useQuery({
    queryKey: ['hardware-scraps', status],
    queryFn: () => fetchHardwareScrapsClient({ status: status || undefined, pageSize: 50 }),
    placeholderData: keepPreviousData,
  })

  const columns: TableColumnsType<HardwareScrapRecord> = [
    { title: '单号', dataIndex: 'scrap_no', width: 170, className: 'font-mono' },
    {
      title: '报废条件',
      dataIndex: 'scrap_reason',
      width: 120,
      render: (v: HardwareScrapReason) => HARDWARE_SCRAP_REASON_LABEL[v] ?? v,
    },
    { title: '发起部门', dataIndex: 'dept_name', width: 110 },
    { title: '发起人', dataIndex: 'requested_by', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 95,
      render: (v: HardwareScrapStatus) => (
        <StatusTag
          tone={SCRAP_STATUS_TONE[v] ?? 'default'}
          label={HARDWARE_SCRAP_STATUS_LABEL[v] ?? v}
        />
      ),
    },
    {
      title: '审批人',
      dataIndex: 'approver_name',
      width: 100,
      render: (v: string | null, r) => r.approved_by || v || '—',
    },
    { title: '出库人', dataIndex: 'executed_by', width: 100, render: (v) => v || '—' },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 115,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 230,
      fixed: 'right',
      render: (_, r) => (
        <ScrapRowActions
          scrap={r}
          actions={scrapActions}
          onDetail={setDetailId}
          onExecute={setExecutingId}
        />
      ),
    },
  ]

  return (
    <SectionCard
      title="报废单"
      description="报废限四条件：超有效期/破损污染变质/工艺淘汰/技术鉴定失效；流程同申领——提交即预扣，审批人通过后进待出库，仓管点「出库」才扣库存，驳回不动账。"
      action={
        canManage && (
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            发起报废
          </Button>
        )
      }
    >
      <QueryFilter
        common={
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ width: 180 }}
            value={status}
            onChange={(v) => setStatus(v)}
            options={Object.entries(HARDWARE_SCRAP_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
          />
        }
      />
      <Table
        rowKey="id"
        size="middle"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={columns}
        locale={{ emptyText: <EmptyGuide compact title="暂无报废单" description="满足报废四条件的物资可发起报废审批" /> }}
        pagination={{ total: list.data?.total ?? 0, pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 1150 }}
      />
      <ScrapDetailDrawer scrapId={detailId} onClose={() => setDetailId(null)} />
      <ScrapExecuteModal
        scrapId={executingId}
        loading={scrapActions.executing}
        onConfirm={(id) => {
          scrapActions.execute(id)
          setExecutingId(null)
        }}
        onClose={() => setExecutingId(null)}
      />
      <ScrapCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => setCreateOpen(false)}
      />
    </SectionCard>
  )
}

/** 发起报废（台账入口）：确定即创建并提交，同申领——预扣生效，进「申请单据 → 待审批」。 */
function ScrapCreateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  // 预扣/在手、申请单据合并列表与统计卡、台账报废列表一起刷新
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware'] })
    queryClient.invalidateQueries({ queryKey: ['hardware-scraps'] })
  }
  const [rows, setRows] = useState<Array<{ material_id: string; name: string; quantity: number }>>([])
  const [approverId, setApproverId] = useState<string | undefined>(undefined)
  const [approverKeyword, setApproverKeyword] = useState('')
  const materials = useQuery({
    queryKey: ['hardware-materials-for-scrap'],
    queryFn: () => fetchHardwareMaterialsClient('', 200),
    enabled: open,
  })
  const { data: approvers = [], isFetching: approversLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'scrap-approvers', approverKeyword],
    queryFn: () =>
      fetchScrapApproversClient({
        keyword: approverKeyword || undefined,
        limit: 50,
      }),
    enabled: open,
    staleTime: 60_000,
  })
  const approverOptions = approvers.map((a) => ({
    value: a.user_id,
    label: `${a.supervisor ? '【主管及以上】' : ''}${a.name}（${a.department || '未匹配部门'} · ${a.position || '—'}）`,
  }))
  const selectedApprover = approvers.find((a) => a.user_id === approverId) ?? null

  const createMut = useMutation({
    mutationFn: async (payload: Parameters<typeof createHardwareScrapClient>[0]) => {
      const created = await createHardwareScrapClient(payload)
      try {
        return await submitHardwareScrapClient(created.id)
      } catch (e) {
        // 提交失败（如可报废量不足）：单据留在草稿，可在「申请单据 → 全部」重新提交
        const tip = e instanceof Error ? e.message : '提交失败'
        throw new Error(`${tip}（报废单 ${created.scrap_no} 已留在草稿，可重新提交）`)
      }
    },
    onSuccess: (submitted) => {
      message.success(
        submitted.approval_channel === 'feishu'
          ? '已提交（预扣生效），飞书审批单已发给所选审批人；审批通过后由仓管出库'
          : '已提交（预扣生效），等审批人在「申请单据 → 待审批」点通过',
      )
      form.resetFields()
      setRows([])
      setApproverId(undefined)
      invalidate()
      onCreated()
    },
    onError: (e: Error) => {
      message.error(e.message, 6)
      // 草稿可能已建：刷新列表让用户看得到那张草稿
      invalidate()
    },
  })

  const submit = async () => {
    const values = await form.validateFields()
    if (!rows.length) {
      message.warning('请至少添加一行报废明细')
      return
    }
    if (!selectedApprover) {
      message.error('请选择审批人（主管及以上）后再提交')
      return
    }
    createMut.mutate({
      dept_name: values.dept_name,
      requested_by: values.requested_by,
      approver_user_id: selectedApprover.user_id,
      approver_name: selectedApprover.name,
      scrap_reason: values.scrap_reason,
      reason_note: values.reason_note,
      remark: values.remark,
      items: rows.map((r) => ({ material_id: r.material_id, quantity: r.quantity })),
    })
  }

  return (
    <Modal
      title="发起报废"
      open={open}
      onCancel={onClose}
      onOk={submit}
      confirmLoading={createMut.isPending}
      okText="发起报废"
      okButtonProps={{ danger: true }}
      width={680}
      destroyOnHidden
    >
      <div className="mb-3 rounded bg-yellow-50 px-3 py-2 text-[13px] text-yellow-700">
        确定后立即提交并预扣，报废单进入「申请单据 → 待审批」；审批人通过后进待发料，仓管点「出库」才真正扣库存。
      </div>
      <Form form={form} layout="vertical" className="mt-2">
        <Space wrap>
          <Form.Item name="dept_name" label="发起部门" rules={[{ required: true }]}>
            <Input style={{ width: 160 }} placeholder="如 发酵 / 仓储部" />
          </Form.Item>
          <Form.Item name="requested_by" label="发起人" rules={[{ required: true }]}>
            <Input style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="scrap_reason" label="报废条件（四选一）" rules={[{ required: true }]}>
            <Select
              style={{ width: 180 }}
              options={Object.entries(HARDWARE_SCRAP_REASON_LABEL).map(([v, l]) => ({ value: v, label: l }))}
            />
          </Form.Item>
        </Space>
        <Form.Item name="reason_note" label="原因说明">
          <Input.TextArea rows={2} placeholder="报废原因/技术鉴定结论等" />
        </Form.Item>
        <Form.Item label="审批人（主管及以上）" required>
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
          />
        </Form.Item>
      </Form>
      <div className="space-y-2">
        <div className="text-[13px] font-medium">报废明细（仅共用类；数量大于 0）</div>
        <Select
          showSearch
          placeholder="搜索物料添加行（名称/规格）"
          style={{ width: '100%' }}
          filterOption={(input, option) =>
            String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
          }
          value={null}
          onChange={(mid: string) => {
            const m = (materials.data?.items ?? []).find((x) => x.id === mid)
            if (!m) return
            setRows((prev) =>
              prev.some((r) => r.material_id === mid)
                ? prev
                : [...prev, { material_id: mid, name: m.name, quantity: 1 }],
            )
          }}
          options={(materials.data?.items ?? []).map((m) => ({
            value: m.id,
            label: `${m.name}${m.spec ? ` ${m.spec}` : ''}`,
          }))}
        />
        {rows.map((r, i) => (
          <Space key={r.material_id} wrap>
            <span>{r.name}</span>
            <InputNumber
              min={1}
              precision={0}
              value={r.quantity}
              onChange={(v) =>
                setRows((prev) =>
                  prev.map((x, xi) => (xi === i ? { ...x, quantity: Number(v) || 0 } : x)),
                )
              }
            />
            <Button
              size="small"
              danger
              onClick={() => setRows((prev) => prev.filter((_, xi) => xi !== i))}
            >
              移除
            </Button>
          </Space>
        ))}
      </div>
    </Modal>
  )
}
