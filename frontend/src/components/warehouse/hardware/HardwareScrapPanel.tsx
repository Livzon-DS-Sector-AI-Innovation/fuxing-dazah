'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
} from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'
import {
  approveHardwareScrapClient,
  cancelHardwareScrapClient,
  createHardwareScrapClient,
  deptConfirmHardwareScrapClient,
  fetchHardwareMaterialsClient,
  fetchHardwareScrapClient,
  fetchHardwareScrapsClient,
  rejectHardwareScrapClient,
  submitHardwareScrapClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_SCRAP_REASON_LABEL,
  HARDWARE_SCRAP_STATUS_LABEL,
  type HardwareScrapRecord,
  type HardwareScrapReason,
  type HardwareScrapStatus,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { EmptyGuide, QueryFilter, SectionCard, StatusTag } from '@/components/warehouse'
import { SCRAP_STATUS_TONE } from './constants'
import { formatQty } from './format'

export function HardwareScrapPanel() {
  const { message, modal } = App.useApp()
  const qc = useQueryClient()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:scrap:manage')
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const list = useQuery({
    queryKey: ['hardware-scraps', status],
    queryFn: () => fetchHardwareScrapsClient({ status: status || undefined, pageSize: 50 }),
    placeholderData: keepPreviousData,
  })
  const detail = useQuery({
    queryKey: ['hardware-scrap', detailId],
    queryFn: () => fetchHardwareScrapClient(detailId!),
    enabled: !!detailId,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hardware-scraps'] })
    qc.invalidateQueries({ queryKey: ['hardware-scrap'] })
  }

  const submitMut = useMutation({
    mutationFn: (id: string) => submitHardwareScrapClient(id),
    onSuccess: () => {
      message.success('已提交审批（待部门主管确认）')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })
  const deptMut = useMutation({
    mutationFn: (id: string) => deptConfirmHardwareScrapClient(id, '部门主管'),
    onSuccess: () => {
      message.success('部门主管已确认（待仓储负责人终审）')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })
  const approveMut = useMutation({
    mutationFn: (id: string) => approveHardwareScrapClient(id, '仓储负责人'),
    onSuccess: () => {
      message.success('终审通过，已销账')
      invalidate()
      setDetailId(null)
    },
    onError: (e: Error) => message.error(e.message),
  })
  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectHardwareScrapClient(id, '审批人', reason),
    onSuccess: () => {
      message.success('已驳回（零动账）')
      invalidate()
      setDetailId(null)
    },
    onError: (e: Error) => message.error(e.message),
  })
  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelHardwareScrapClient(id),
    onSuccess: () => {
      message.success('已撤回')
      invalidate()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const askReject = (id: string) => {
    let reason = ''
    modal.warning({
      title: '驳回报废单',
      content: (
        <Input.TextArea
          placeholder="驳回原因"
          onChange={(e) => {
            reason = e.target.value
          }}
        />
      ),
      onOk: () => rejectMut.mutate({ id, reason: reason || '未填写原因' }),
    })
  }

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
      width: 140,
      render: (v: HardwareScrapStatus) => (
        <StatusTag tone={SCRAP_STATUS_TONE[v] ?? 'default'} label={HARDWARE_SCRAP_STATUS_LABEL[v] ?? v} />
      ),
    },
    {
      title: '部门主管',
      dataIndex: 'dept_confirmed_by',
      width: 110,
      render: (v) => v || '—',
    },
    { title: '终审', dataIndex: 'approved_by', width: 110, render: (v) => v || '—' },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 115,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      fixed: 'right',
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => setDetailId(r.id)}>
            详情
          </Button>
          {canManage && r.status === 'draft' && (
            <Button size="small" type="primary" onClick={() => submitMut.mutate(r.id)}>
              提交审批
            </Button>
          )}
          {canManage && r.status === 'pending_dept' && (
            <Button size="small" type="primary" onClick={() => deptMut.mutate(r.id)}>
              部门主管确认
            </Button>
          )}
          {canManage && r.status === 'pending_final' && (
            <>
              <Button size="small" type="primary" danger onClick={() => approveMut.mutate(r.id)}>
                终审销账
              </Button>
              <Button size="small" danger onClick={() => askReject(r.id)}>
                驳回
              </Button>
            </>
          )}
          {canManage && r.status === 'pending_dept' && (
            <Button size="small" danger onClick={() => askReject(r.id)}>
              驳回
            </Button>
          )}
          {canManage && ['draft', 'pending_dept', 'pending_final'].includes(r.status) && (
            <Button size="small" onClick={() => cancelMut.mutate(r.id)}>
              撤回
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <SectionCard
      title="报废单"
      description="报废限四条件：超有效期/破损污染变质/工艺淘汰/技术鉴定失效；终审通过即销账，驳回不动账。"
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
        scroll={{ x: 1100 }}
      />
      <Drawer
        title={detail.data ? `报废单 ${detail.data.scrap_no}` : '报废单详情'}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        width={640}
      >
        {detail.data && (
          <div className="space-y-3">
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="报废条件">
                {HARDWARE_SCRAP_REASON_LABEL[detail.data.scrap_reason]}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag tone={SCRAP_STATUS_TONE[detail.data.status] ?? 'default'} label={HARDWARE_SCRAP_STATUS_LABEL[detail.data.status]} />
              </Descriptions.Item>
              <Descriptions.Item label="发起">
                {detail.data.dept_name} / {detail.data.requested_by}
              </Descriptions.Item>
              <Descriptions.Item label="说明">{detail.data.reason_note || '—'}</Descriptions.Item>
              <Descriptions.Item label="部门主管">
                {detail.data.dept_confirmed_by || '—'}
              </Descriptions.Item>
              <Descriptions.Item label="终审">{detail.data.approved_by || '—'}</Descriptions.Item>
            </Descriptions>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detail.data.items ?? []}
              columns={[
                { title: '品名', dataIndex: 'name' },
                { title: '规格', dataIndex: 'spec', render: (v) => v || '—' },
                { title: '数量', dataIndex: 'quantity', width: 90, render: (v: unknown) => formatQty(v) },
                {
                  title: '批次',
                  dataIndex: 'preferred_lot_id',
                  width: 120,
                  render: (v) => (v ? '指定批次' : 'FIFO 自动'),
                },
              ] as TableColumnsType<NonNullable<HardwareScrapRecord['items']>[number]>}
            />
            {detail.data.lot_allocations && detail.data.lot_allocations.length > 0 && (
              <div className="text-[12px] text-[var(--color-steel)]">
                销账批次：{detail.data.lot_allocations.map((a) => `${a.lot_no ?? ''}×${formatQty(a.qty)}`).join('，')}
              </div>
            )}
            {detail.data.rejected_reason && (
              <div className="text-[13px] text-red-600">驳回原因：{detail.data.rejected_reason}</div>
            )}
          </div>
        )}
      </Drawer>
      <ScrapCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false)
          invalidate()
        }}
      />
    </SectionCard>
  )
}

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
  const [form] = Form.useForm()
  const [rows, setRows] = useState<Array<{ material_id: string; name: string; quantity: number }>>([])
  const materials = useQuery({
    queryKey: ['hardware-materials-for-scrap'],
    queryFn: () => fetchHardwareMaterialsClient('', 200),
  })

  const createMut = useMutation({
    mutationFn: (payload: Parameters<typeof createHardwareScrapClient>[0]) =>
      createHardwareScrapClient(payload),
    onSuccess: () => {
      message.success('报废单已发起（草稿）')
      form.resetFields()
      setRows([])
      onCreated()
    },
    onError: (e: Error) => message.error(e.message),
  })

  const submit = async () => {
    const values = await form.validateFields()
    if (!rows.length) {
      message.warning('请至少添加一行报废明细')
      return
    }
    createMut.mutate({
      dept_name: values.dept_name,
      requested_by: values.requested_by,
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
      width={680}
      destroyOnClose
    >
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
