'use client'

// 五金库领用中心（M3，车间视角）：发起申请（物料搜索+库存可见）/
// 我的申请+全部单据 / 部门月度统计。审批双通道：manual=主管在此点确认；
// 发料走仓管员发料台（出入库工作台）。设计 §七。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  approveHardwareRequisitionClient,
  cancelHardwareRequisitionClient,
  createHardwareRequisitionClient,
  fetchHardwareMaterialsClient,
  fetchHardwareMovementsClient,
  fetchHardwareRequisitionsClient,
  fetchHardwareStockClient,
  fetchHardwareStockSummaryClient,
  rejectHardwareRequisitionClient,
  submitHardwareRequisitionClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_REQ_STATUS_LABEL,
  HARDWARE_REQ_TYPE_LABEL,
  type HardwareRequisitionRecord,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { QueryFilter, SectionCard, StatCard, StatusTag } from '@/components/warehouse'

type TabKey = 'browse' | 'mine' | 'dept'

const REQ_STATUS_TONE = {
  draft: 'default',
  pending: 'warn',
  approved: 'info',
  issued: 'ok',
  rejected: 'danger',
  cancelled: 'default',
  overdue_unpatched: 'danger',
} as const

export function HardwareRequisitions() {
  const [tab, setTab] = useState<TabKey>('browse')
  return (
    <div className="flex flex-col gap-4">
      <SectionCard title="五金库领用">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[17px] font-semibold">五金库领用中心</div>
            <div className="text-[13px] text-gray-500">
              共用类领料走审批（提交即预扣）；车间单独需求类到货直接领取，无需申请
            </div>
          </div>
          <Segmented
            value={tab}
            onChange={(v) => setTab(v as TabKey)}
            options={[
              { value: 'browse', label: '查库存' },
              { value: 'mine', label: '领用申请' },
              { value: 'dept', label: '部门月度统计' },
            ]}
          />
        </div>
      </SectionCard>
      {tab === 'browse' && <BrowsePanel />}
      {tab === 'mine' && <MyRequisitionsPanel />}
      {tab === 'dept' && <DeptStatsPanel />}
    </div>
  )
}

// ── 查库存 + 发起申请 ──

function BrowsePanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('warehouse:hardware:requisition:create')

  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [lowOnly, setLowOnly] = useState(false)
  const [applying, setApplying] = useState<{ id: string; name: string; available: number; unit: string } | null>(
    null,
  )

  const { data: summary } = useQuery({
    queryKey: ['warehouse', 'hardware', 'summary'],
    queryFn: fetchHardwareStockSummaryClient,
  })

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'stock', { keyword, page, pageSize, lowOnly }],
    queryFn: () =>
      fetchHardwareStockClient({
        keyword: keyword || undefined,
        low_only: lowOnly,
        page,
        pageSize,
      }),
    placeholderData: keepPreviousData,
  })

  const columns: TableColumnsType<NonNullable<typeof res>['items'][number]> = [
    {
      title: '物资名称',
      dataIndex: 'name',
      width: 200,
    },
    { title: '规格型号', dataIndex: 'spec', width: 130, render: (v: unknown) => (v as string) || '-' },
    { title: '单位', dataIndex: 'unit', width: 60, render: (v: unknown) => (v as string) || '' },
    {
      title: '可用',
      dataIndex: 'available',
      width: 90,
      align: 'right',
      render: (v: number, r) => (
        <span className={r.is_low ? 'font-semibold text-red-600' : 'font-medium'}>
          {Number(v).toLocaleString()}
        </span>
      ),
    },
    { title: '在手', dataIndex: 'on_hand', width: 80, align: 'right' },
    { title: '预扣', dataIndex: 'reserved', width: 80, align: 'right' },
    {
      title: '操作',
      width: 110,
      render: (_: unknown, r) =>
        canCreate && r.material.managed_class === 'stocked' ? (
          <Button
            size="small"
            disabled={Number(r.available) <= 0}
            onClick={() =>
              setApplying({
                id: r.material.id,
                name: r.name ?? '',
                available: Number(r.available),
                unit: r.unit ?? '',
              })
            }
          >
            申领
          </Button>
        ) : (
          <span className="text-[12px] text-gray-400">
            {r.material.managed_class === 'direct' ? '到货直领' : '-'}
          </span>
        ),
    },
  ]

  return (
    <SectionCard title={`库存查询（${summary?.low_count ?? 0} 种预警）`}>
      <QueryFilter
        common={
          <>
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: '#999' }} />}
              placeholder="名称 / 规格（如 DN25 阀门）"
              style={{ width: 260 }}
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value)
                setPage(1)
              }}
            />
            <Segmented
              value={lowOnly ? 'low' : 'none'}
              onChange={(v) => {
                setLowOnly(v === 'low')
                setPage(1)
              }}
              options={[
                { value: 'none', label: '全部' },
                { value: 'low', label: '仅看预警' },
              ]}
            />
          </>
        }
      />
      <Table
        size="small"
        rowKey={(r) => r.material.id}
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: res?.total ?? 0,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 850 }}
      />
      <ApplyModal apply={applying} onClose={() => setApplying(null)} />
    </SectionCard>
  )
}

function ApplyModal({
  apply,
  onClose,
}: {
  apply: { id: string; name: string; available: number; unit: string } | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const onSubmit = async () => {
    if (!apply) return
    const values = await form.validateFields()
    setSaving(true)
    try {
      const created = await createHardwareRequisitionClient({
        dept_name: values.dept_name,
        applicant: values.applicant,
        purpose: values.purpose,
        req_type: values.req_type,
        items: [{ material_id: apply.id, need_qty: values.need_qty }],
      })
      await submitHardwareRequisitionClient(created.id)
      message.success('申请已提交（预扣生效，等待审批）')
      form.resetFields()
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'stock'] })
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '提交失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`申领 · ${apply?.name ?? ''}`}
      open={!!apply}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={saving}
      okText="提交申请（预扣）"
      width={460}
    >
      {apply && (
        <div className="mb-3 rounded bg-gray-50 px-3 py-2 text-[13px]">
          当前可用 {apply.available} {apply.unit}（提交即预扣，审批通过后到发料台领料）
        </div>
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ req_type: 'normal', applicant: '' }}
      >
        <Form.Item name="dept_name" label="领用部门" rules={[{ required: true, message: '请输入部门' }]}>
          <Input placeholder="如：发酵 / 提炼一期 / 精制机修" />
        </Form.Item>
        <Form.Item name="applicant" label="领用人" rules={[{ required: true, message: '请输入姓名' }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="need_qty"
          label="需求数量"
          rules={[{ required: true, message: '请输入数量' }]}
        >
          <InputNumber
            min={0.001}
            precision={3}
            max={apply?.available}
            style={{ width: '100%' }}
            addonAfter={apply?.unit}
          />
        </Form.Item>
        <Form.Item name="req_type" label="类型">
          <Select
            options={[
              { value: 'normal', label: '常规' },
              { value: 'urgent', label: '紧急（先发后补 24h）' },
              { value: 'excess', label: '超额（超月需求）' },
            ]}
          />
        </Form.Item>
        <Form.Item name="purpose" label="用途">
          <Input.TextArea rows={2} placeholder="如：3# 反应釜出口管更换" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 领用申请列表（申请人/主管共用：manual 审批在此确认）──

function MyRequisitionsPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canApprove = hasPermission('warehouse:hardware:requisition:approve')

  const [statusFilter, setStatusFilter] = useState<string | undefined>('pending')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detail, setDetail] = useState<HardwareRequisitionRecord | null>(null)

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'requisitions', { statusFilter, page, pageSize }],
    queryFn: () => fetchHardwareRequisitionsClient({ status: statusFilter, page, pageSize }),
    placeholderData: keepPreviousData,
  })

  const approve = useMutation({
    mutationFn: (id: string) => approveHardwareRequisitionClient(id, '部门主管（web 代录）'),
    onSuccess: () => {
      message.success('已审批通过（预扣保持，待仓管员发料）')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
    },
    onError: (e) => message.error(e instanceof Error ? e.message : '审批失败'),
  })

  const reject = useMutation({
    mutationFn: (id: string) =>
      rejectHardwareRequisitionClient(id, '部门主管（web 代录）', '主管驳回'),
    onSuccess: () => {
      message.success('已驳回（预扣已释放）')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
    },
    onError: (e) => message.error(e instanceof Error ? e.message : '驳回失败'),
  })

  const columns: TableColumnsType<HardwareRequisitionRecord> = [
    { title: '单号', dataIndex: 'req_no', width: 150 },
    {
      title: '类型',
      dataIndex: 'req_type',
      width: 70,
      render: (v: string) =>
        v === 'urgent' ? (
          <Tag color="red">紧急</Tag>
        ) : v === 'excess' ? (
          <Tag color="orange">超额</Tag>
        ) : (
          <Tag>常规</Tag>
        ),
    },
    { title: '部门', dataIndex: 'dept_name', width: 100 },
    { title: '申请人', dataIndex: 'applicant', width: 90 },
    { title: '用途', dataIndex: 'purpose', render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => (
        <StatusTag
          tone={REQ_STATUS_TONE[v as keyof typeof REQ_STATUS_TONE] ?? 'default'}
          label={HARDWARE_REQ_STATUS_LABEL[v as keyof typeof HARDWARE_REQ_STATUS_LABEL] ?? v}
        />
      ),
    },
    { title: '审批人', dataIndex: 'approved_by', width: 110, render: (v) => v || '-' },
    {
      title: '申请时间',
      dataIndex: 'created_at',
      width: 120,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 180,
      render: (_: unknown, r) => (
        <Space>
          <Button size="small" onClick={() => setDetail(r)}>
            明细
          </Button>
          {r.status === 'pending' && canApprove && (
            <>
              <Button size="small" type="primary" loading={approve.isPending} onClick={() => approve.mutate(r.id)}>
                通过
              </Button>
              <Button size="small" danger loading={reject.isPending} onClick={() => reject.mutate(r.id)}>
                驳回
              </Button>
            </>
          )}
          {(r.status === 'draft' || r.status === 'pending') && (
            <Button
              size="small"
              onClick={async () => {
                await cancelHardwareRequisitionClient(r.id)
                message.success('已取消')
                queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
              }}
            >
              取消
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <SectionCard title="领用申请（manual 审批通道：主管在此确认代录）">
      <QueryFilter
        common={
          <Segmented
            value={statusFilter ?? 'all'}
            onChange={(v) => {
              setStatusFilter(v === 'all' ? undefined : (v as string))
              setPage(1)
            }}
            options={[
              { value: 'pending', label: '待审批' },
              { value: 'approved', label: '待发料' },
              { value: 'issued', label: '已发料' },
              { value: 'rejected', label: '已驳回' },
              { value: 'all', label: '全部' },
            ]}
          />
        }
      />
      <Table<HardwareRequisitionRecord>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: res?.total ?? 0,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 1100 }}
      />
      <RequisitionDetailModal record={detail} onClose={() => setDetail(null)} />
    </SectionCard>
  )
}

function RequisitionDetailModal({
  record,
  onClose,
}: {
  record: HardwareRequisitionRecord | null
  onClose: () => void
}) {
  if (!record) return null
  return (
    <Modal
      title={`${record.req_no}（${record.status}）`}
      open={!!record}
      onCancel={onClose}
      footer={null}
      width={640}
    >
      <div className="text-[13px] leading-7">
        <div>部门：{record.dept_name}　申请人：{record.applicant}　类型：{HARDWARE_REQ_TYPE_LABEL[record.req_type]}</div>
        <div>用途：{record.purpose || '-'}</div>
        {record.approval_note && <div>审批备注：{record.approval_note}</div>}
        {record.rejected_reason && <div>驳回原因：{record.rejected_reason}</div>}
        {record.urgent_patch_deadline && (
          <div>补单截止：{dayjs(record.urgent_patch_deadline).format('MM-DD HH:mm')}</div>
        )}
      </div>
      <Table
        size="small"
        rowKey="id"
        className="mt-3"
        dataSource={record.items}
        pagination={false}
        columns={[
          { title: '物料', dataIndex: 'material_name' },
          { title: '规格', dataIndex: 'spec', width: 120, render: (v) => v || '-' },
          { title: '需求数', dataIndex: 'need_qty', width: 90, align: 'right' },
          {
            title: '实发数',
            dataIndex: 'issued_qty',
            width: 90,
            align: 'right',
            render: (v: number | null) => v ?? '-',
          },
          {
            title: '批次分配',
            dataIndex: 'fifo_lot_allocations',
            render: (v: Array<{ lot_no: string; qty: number }> | null) =>
              v?.length ? (
                <span className="font-mono text-[12px]">
                  {v.map((a) => `${a.lot_no}×${a.qty}`).join(' + ')}
                </span>
              ) : (
                '-'
              ),
          },
        ]}
      />
    </Modal>
  )
}

// ── 部门月度统计 ──

function DeptStatsPanel() {
  const [dept, setDept] = useState('发酵')

  const { data: res } = useQuery({
    queryKey: ['warehouse', 'hardware', 'movements', 'dept-month', dept],
    queryFn: () =>
      fetchHardwareMovementsClient({
        direction: 'outbound',
        dept_name: dept,
        page: 1,
        pageSize: 200,
      }),
  })

  const monthly = useMemo(() => {
    const monthStart = dayjs().startOf('month')
    const agg = new Map<string, { qty: number; count: number; unit: string }>()
    for (const mv of res?.items ?? []) {
      if (dayjs(mv.occurred_at).isBefore(monthStart)) continue
      const key = mv.material_name
      const prev = agg.get(key) ?? { qty: 0, count: 0, unit: mv.unit || '' }
      agg.set(key, { qty: prev.qty + Number(mv.quantity), count: prev.count + 1, unit: mv.unit || '' })
    }
    return [...agg.entries()].sort((a, b) => b[1].qty - a[1].qty)
  }, [res])

  return (
    <SectionCard
      title="部门月度领用统计"
      action={
        <Input
          style={{ width: 160 }}
          value={dept}
          onChange={(e) => setDept(e.target.value)}
          placeholder="部门名（如：发酵）"
        />
      }
    >
      <Table
        size="small"
        rowKey={(r) => r[0]}
        dataSource={monthly}
        pagination={false}
        columns={[
          { title: '物料', dataIndex: 0 },
          { title: '本月领用量', render: (_: unknown, r) => Number(r[1].qty).toLocaleString() },
          { title: '单位', render: (_: unknown, r) => r[1].unit },
          { title: '领用次数', render: (_: unknown, r) => r[1].count },
        ]}
      />
    </SectionCard>
  )
}
