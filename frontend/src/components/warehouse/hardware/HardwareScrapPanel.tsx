'use client'

// 五金库报废面板（三期 M7）：发起（四条件单选+明细行）→ ①部门主管确认 →
// ②仓储负责人终审（通过即销账）→ 台账；驳回/撤回零动账。
// 设计 §十一 三期 M7；ApprovalChannel manual 两步，feishu 通道制度定稿后切配置。

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
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
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

const SCRAP_STATUS_COLOR: Record<HardwareScrapStatus, string> = {
  draft: 'default',
  pending_dept: 'gold',
  pending_final: 'orange',
  approved: 'green',
  rejected: 'red',
  cancelled: 'default',
}

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
      message.success('终审通过，已销账（FIFO 扣批次 + scrap 流水）')
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
      title: '驳回报废单（零动账）',
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
    { title: '单号', dataIndex: 'scrap_no', width: 170 },
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
        <Tag color={SCRAP_STATUS_COLOR[v]}>{HARDWARE_SCRAP_STATUS_LABEL[v] ?? v}</Tag>
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
      width: 150,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
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
    <div className="space-y-3">
      <Space wrap>
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 180 }}
          value={status}
          onChange={(v) => setStatus(v)}
          options={Object.entries(HARDWARE_SCRAP_STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))}
        />
        {canManage && (
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            发起报废
          </Button>
        )}
        <Typography.Text type="secondary">
          制度 5.6 四条件（超有效期/破损污染变质/工艺淘汰/技术鉴定失效）；终审通过即 FIFO 销账，驳回零动账。
        </Typography.Text>
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        columns={columns}
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
                <Tag color={SCRAP_STATUS_COLOR[detail.data.status]}>
                  {HARDWARE_SCRAP_STATUS_LABEL[detail.data.status]}
                </Tag>
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
                { title: '数量', dataIndex: 'quantity', width: 90 },
                {
                  title: '批次',
                  dataIndex: 'preferred_lot_id',
                  width: 120,
                  render: (v) => (v ? '指定批次' : 'FIFO 自动'),
                },
              ] as TableColumnsType<NonNullable<HardwareScrapRecord['items']>[number]>}
            />
            {detail.data.lot_allocations && detail.data.lot_allocations.length > 0 && (
              <Typography.Text type="secondary">
                销账批次：{detail.data.lot_allocations.map((a) => `${a.lot_no ?? ''}×${a.qty}`).join('，')}
              </Typography.Text>
            )}
            {detail.data.rejected_reason && (
              <Typography.Text type="danger">驳回原因：{detail.data.rejected_reason}</Typography.Text>
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
    </div>
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
    queryFn: () => fetchHardwareMaterialsClient('', 500),
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
      title="发起报废（制度 5.6）"
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
        <Typography.Text strong>报废明细（仅共用类 stocked；数量&gt;0）</Typography.Text>
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
            <Typography.Text>{r.name}</Typography.Text>
            <InputNumber
              min={0.001}
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
