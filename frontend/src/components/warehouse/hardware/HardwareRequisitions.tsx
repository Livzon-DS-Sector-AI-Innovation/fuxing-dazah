'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
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
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  approveHardwareRequisitionClient,
  cancelHardwareRequisitionClient,
  createHardwareRequisitionClient,
  exportRequisitionsUrl,
  fetchHardwareMovementsClient,
  fetchHardwareRequisitionsClient,
  fetchHardwareStockClient,
  fetchHardwareStockDetailClient,
  fetchHardwareStockSummaryClient,
  fetchRequisitionApproversClient,
  issueHardwareRequisitionClient,
  rejectHardwareRequisitionClient,
  submitHardwareRequisitionClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_REQ_STATUS_LABEL,
  HARDWARE_REQ_TYPE_LABEL,
  type HardwareRequisitionRecord,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { getCurrentUser } from '@/actions/auth'
import type { User } from '@/types/user'
import { QueryFilter, SectionCard, StatusTag, EmptyGuide } from '@/components/warehouse'
import { REQ_STATUS_TONE, REQ_TYPE_TONE } from './constants'
import { formatQty } from './format'

type TabKey = 'browse' | 'mine' | 'dept'

export function HardwareRequisitions({ focusStatus }: { focusStatus?: string }) {
  const [tab, setTab] = useState<TabKey>(focusStatus ? 'mine' : 'browse')
  return (
    <div className="flex flex-col gap-4">
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as TabKey)}
        options={[
          { value: 'browse', label: '申领库存' },
          { value: 'mine', label: '申请单据' },
          { value: 'dept', label: '部门统计' },
        ]}
      />
      {tab === 'browse' && <BrowsePanel />}
      {tab === 'mine' && <MyRequisitionsPanel focusStatus={focusStatus} />}
      {tab === 'dept' && <DeptStatsPanel />}
    </div>
  )
}

function BrowsePanel() {
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('warehouse:hardware:requisition:create')

  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [lowOnly, setLowOnly] = useState(false)
  const [applying, setApplying] = useState<{
    id: string
    name: string
    category: string
    spec: string
    unit: string
    available: number
  } | null>(null)

  const { data: summary } = useQuery({
    queryKey: ['warehouse', 'hardware', 'summary'],
    queryFn: fetchHardwareStockSummaryClient,
    refetchInterval: 30_000,
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
    refetchInterval: 30_000,
  })

  const columns: TableColumnsType<NonNullable<typeof res>['items'][number]> = [
    {
      title: '物资名称',
      dataIndex: 'name',
      width: 180,
      ellipsis: true,
    },
    { title: '规格型号', dataIndex: 'spec', width: 150, ellipsis: true, render: (v: unknown) => (v as string) || '-' },
    { title: '单位', dataIndex: 'unit', width: 60, render: (v: unknown) => (v as string) || '' },
    {
      title: '可用',
      dataIndex: 'available',
      width: 90,
      align: 'right',
      render: (v: unknown, r) => (
        <span className={`tabular-nums ${r.is_low ? 'font-semibold text-red-600' : 'font-medium'}`}>
          {formatQty(v)}
        </span>
      ),
    },
    { title: '在手', dataIndex: 'on_hand', width: 80, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
    { title: '预扣', dataIndex: 'reserved', width: 80, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
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
                category: r.category ?? r.material.category ?? '',
                spec: r.spec ?? '',
                unit: r.unit ?? '',
                available: Number(r.available),
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
        size="middle"
        rowKey={(r) => r.material.id}
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        locale={{ emptyText: <EmptyGuide compact title="暂无库存数据" description="调整关键词或查看全部类别" /> }}
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
  apply: {
    id: string
    name: string
    category: string
    spec: string
    unit: string
    available: number
  } | null
  onClose: () => void
}) {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [me, setMe] = useState<User | null>(null)
  const [approverId, setApproverId] = useState<string | undefined>(undefined)
  const [approverKeyword, setApproverKeyword] = useState('')
  const reqType = Form.useWatch('req_type', form)

  const { data: approvers = [], isFetching: approversLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'approvers', approverKeyword],
    queryFn: () =>
      fetchRequisitionApproversClient({
        keyword: approverKeyword || undefined,
        limit: 50,
      }),
    enabled: !!apply,
    staleTime: 60_000,
  })
  const approverOptions = approvers.map((a) => ({
    value: a.user_id,
    label: `${a.supervisor ? '【主管及以上】' : ''}${a.name}（${a.department || '未匹配部门'} · ${a.position || '—'}）`,
  }))
  const selectedApprover = approvers.find((a) => a.user_id === approverId) ?? null

  useEffect(() => {
    let alive = true
    getCurrentUser()
      .then((u) => alive && setMe(u))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  const deptName = me?.department?.trim() || '未匹配部门'

  const submitConfirmed = async (values: {
    need_qty: number
    req_type: 'normal' | 'urgent' | 'excess'
    urgent_reason?: string
  }) => {
    if (!apply) return
    setSaving(true)
    let createdId: string | null = null
    try {
      const created = await createHardwareRequisitionClient({
        dept_name: deptName,
        applicant: me!.name,
        approver_user_id: selectedApprover?.user_id,
        approver_name: selectedApprover?.name,
        req_type: values.req_type,
        urgent_reason: values.req_type === 'urgent' ? values.urgent_reason : undefined,
        items: [{ material_id: apply.id, need_qty: values.need_qty }],
      })
      createdId = created.id
      const submitted = await submitHardwareRequisitionClient(created.id)
      if (values.req_type === 'urgent') {
        message.success(
          submitted.approval_channel === 'feishu'
            ? '紧急领料已发起审批（仓管已收到加急通知，审批通过前即可发料；审批单据即闭环手续）'
            : '紧急领料已提交（仓管已收到加急通知，审批通过前即可发料）',
        )
      } else if (submitted.approval_channel === 'feishu') {
        message.success('已在飞书发起「福兴电子领/退料单审批」，审批通过后由仓管员发料')
      } else {
        message.success('申请已提交（预扣生效，等待主管在系统内审批）')
      }
      form.resetFields()
      setApproverId(undefined)
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'stock'] })
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
    } catch (e) {
      const tip = e instanceof Error ? e.message : '提交失败'
      message.error(createdId ? `${tip}（单据已留在「申请单据」草稿，可重新提交）` : tip)
      if (createdId) {
        form.resetFields()
        setApproverId(undefined)
        onClose()
        queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'stock'] })
        queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
      }
    } finally {
      setSaving(false)
    }
  }

  const onSubmit = async () => {
    if (!apply) return
    const values = await form.validateFields()
    if (!me?.name) {
      message.error('当前登录人缺少姓名（账号未同步姓名），请先同步人员信息后再申领')
      return
    }
    if (!selectedApprover) {
      message.error('请选择审批人（主管及以上）后再提交')
      return
    }
    modal.confirm({
      title: '确认发起审批',
      width: 440,
      okText: '确认发起',
      cancelText: '再改改',
      content: (
        <div className="space-y-1 text-[13px]">
          <div>物资：{apply.name}{apply.spec ? ` · ${apply.spec}` : ''}</div>
          <div>领取量：{formatQty(values.need_qty)} {apply.unit}</div>
          <div>类型：{values.req_type === 'urgent' ? '紧急（先发后批）' : '常规'}</div>
          {values.req_type === 'urgent' && <div>紧急原因：{values.urgent_reason || '-'}</div>}
          <div>审批人：{selectedApprover?.name ?? '-'}</div>
          <div className="pt-1 text-[12px] text-gray-500">
            {values.req_type === 'urgent'
              ? '确认后将发起审批并加急通知仓管员；紧急单审批通过前仓管员即可发料（审批单据即闭环手续）。'
              : '确认后将在飞书发起「福兴电子领/退料单审批」，由所选审批人审批。'}
          </div>
        </div>
      ),
      onOk: () => submitConfirmed(values),
    })
  }

  return (
    <Modal
      title={`申领 · ${apply?.name ?? ''}`}
      open={!!apply}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={saving}
      okText="下一步：确认发起"
      width={460}
    >
      {apply && (
        <div className="mb-3 space-y-1 rounded bg-gray-50 px-3 py-2 text-[13px]">
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            <div>类别：{apply.category || '-'}</div>
            <div>物资名称：{apply.name || '-'}</div>
            <div>规格型号：{apply.spec || '-'}</div>
            <div>计量单位：{apply.unit || '-'}</div>
            <div className="font-medium">可领量：{formatQty(apply.available)}</div>
          </div>
          <div className="pt-1 text-[12px] text-gray-500">
            领用部门 / 领用人：{me ? `${deptName} / ${me.name}` : '加载中…'}
            {me && !me.department ? '（账号未同步部门，按「未匹配部门」记录，不影响审批）' : ''}
          </div>
        </div>
      )}
      {reqType === 'urgent' ? (
        <div className="mb-3 rounded bg-orange-50 px-3 py-2 text-[13px] text-orange-600">
          紧急领料（先发后批）：照常发起审批，仓管员会收到加急通知，审批通过前即可发料；
          审批单据本身即闭环手续，无需再补办。
        </div>
      ) : (
        <div className="mb-3 rounded bg-blue-50 px-3 py-2 text-[13px] text-blue-600">
          提交即按审批表单发起「福兴电子领/退料单审批」，审批通过后由仓管员发料。
        </div>
      )}
      <Form form={form} layout="vertical" initialValues={{ req_type: 'normal' }}>
        <Form.Item
          name="need_qty"
          label="领取量"
          rules={[{ required: true, message: '请输入领取量' }]}
        >
          <InputNumber
            min={1}
            precision={0}
            max={apply?.available}
            style={{ width: '100%' }}
            addonAfter={apply?.unit}
          />
        </Form.Item>
        <Form.Item name="req_type" label="类型">
          <Select
            options={[
              { value: 'normal', label: '常规（走审批）' },
              { value: 'urgent', label: '紧急（先发后批）' },
            ]}
          />
        </Form.Item>
        {reqType === 'urgent' && (
          <Form.Item
            name="urgent_reason"
            label="紧急原因"
            rules={[{ required: true, message: '紧急申领必须填写紧急原因' }]}
          >
            <Input placeholder="如：3#泵体抢修急需" maxLength={200} showCount />
          </Form.Item>
        )}
        <Form.Item label="审批人（主管及以上）" required>
          <Select
            showSearch
            placeholder="搜索姓名 / 部门 / 职位后选择审批人"
            value={approverId}
            loading={approversLoading}
            filterOption={false}
            onSearch={(v) => setApproverKeyword(v)}
            onChange={(v: string) => setApproverId(v)}
            options={approverOptions}
            notFoundContent={approversLoading ? '加载中…' : '无匹配人员'}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function MyRequisitionsPanel({ focusStatus }: { focusStatus?: string }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canApprove = hasPermission('warehouse:hardware:requisition:approve')
  const canIssue = hasPermission('warehouse:hardware:requisition:issue')

  const [statusFilter, setStatusFilter] = useState<string | undefined>(focusStatus ?? 'pending')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detail, setDetail] = useState<HardwareRequisitionRecord | null>(null)
  const [issuing, setIssuing] = useState<HardwareRequisitionRecord | null>(null)

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'requisitions', { statusFilter, page, pageSize }],
    queryFn: () => fetchHardwareRequisitionsClient({ status: statusFilter, page, pageSize }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
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

  const resubmit = useMutation({
    mutationFn: (id: string) => submitHardwareRequisitionClient(id),
    onSuccess: (r) => {
      message.success(
        r.approval_channel === 'feishu'
          ? '已重新发起飞书审批（预扣生效）'
          : '已提交（预扣生效，等待主管在系统内审批）',
      )
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'stock'] })
    },
    onError: (e) => message.error(e instanceof Error ? e.message : '提交失败'),
  })

  const columns: TableColumnsType<HardwareRequisitionRecord> = [
    { title: '单号', dataIndex: 'req_no', width: 160, className: 'font-mono' },
    {
      title: '类型',
      dataIndex: 'req_type',
      width: 70,
      render: (v: string) => (
        <StatusTag
          tone={REQ_TYPE_TONE[v as keyof typeof REQ_TYPE_TONE] ?? 'default'}
          label={HARDWARE_REQ_TYPE_LABEL[v as keyof typeof HARDWARE_REQ_TYPE_LABEL] ?? v}
        />
      ),
    },
    { title: '部门', dataIndex: 'dept_name', width: 90 },
    { title: '申请人', dataIndex: 'applicant', width: 85 },
    { title: '用途', dataIndex: 'purpose', width: 100, ellipsis: true, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 95,
      render: (v: string) => (
        <StatusTag
          tone={REQ_STATUS_TONE[v as keyof typeof REQ_STATUS_TONE] ?? 'default'}
          label={HARDWARE_REQ_STATUS_LABEL[v as keyof typeof HARDWARE_REQ_STATUS_LABEL] ?? v}
        />
      ),
    },
    {
      title: '审批人',
      dataIndex: 'approved_by',
      width: 95,
      render: (_: unknown, r: HardwareRequisitionRecord) =>
        r.approved_by || r.approver_name || '-',
    },
    {
      title: '申请时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_: unknown, r) => (
        <Space wrap size={4}>
          <Button size="small" onClick={() => setDetail(r)}>
            明细
          </Button>
          {canIssue && (r.status === 'approved' || (r.req_type === 'urgent' && r.status === 'pending')) && (
            <Button size="small" type="primary" onClick={() => setIssuing(r)}>
              发料
            </Button>
          )}
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
          {r.status === 'draft' && (
            <Button
              size="small"
              type="primary"
              loading={resubmit.isPending}
              onClick={() => resubmit.mutate(r.id)}
            >
              提交审批
            </Button>
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
    <SectionCard
      title="领用申请单"
      action={
        <a href={exportRequisitionsUrl({ status: statusFilter })}>
          <Button size="small" icon={<DownloadOutlined />}>导出 Excel</Button>
        </a>
      }
    >
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
        size="middle"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        locale={{ emptyText: <EmptyGuide compact title="暂无申请单据" description="在「申领库存」中选择物资发起申请" /> }}
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
        scroll={{ x: 1090 }}
      />
      <RequisitionDetailModal record={detail} onClose={() => setDetail(null)} />
      <IssueModal requisition={issuing} onClose={() => setIssuing(null)} />
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
      title={`${record.req_no}`}
      open={!!record}
      onCancel={onClose}
      footer={null}
      width={640}
    >
      <div className="text-[13px] leading-7">
        <div>部门：{record.dept_name}　申请人：{record.applicant}　类型：{HARDWARE_REQ_TYPE_LABEL[record.req_type]}</div>
        <div>用途：{record.purpose || '-'}</div>
        {record.approver_name && <div>指定审批人：{record.approver_name}</div>}
        {record.approval_channel && (
          <div>
            审批通道：{record.approval_channel === 'feishu' ? '飞书「福兴电子领/退料单审批」' : '系统内人工审批'}
            {record.approval_instance_code ? `（实例 ${record.approval_instance_code}）` : ''}
          </div>
        )}
        {record.approval_note && <div>审批备注：{record.approval_note}</div>}
        {record.rejected_reason && <div>驳回原因：{record.rejected_reason}</div>}
        {record.urgent_reason && <div>紧急原因：{record.urgent_reason}</div>}
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
          { title: '需求数', dataIndex: 'need_qty', width: 90, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
          {
            title: '实发数',
            dataIndex: 'issued_qty',
            width: 90,
            align: 'right',
            className: 'tabular-nums',
            render: (v: unknown) => (v == null ? '-' : formatQty(v)),
          },
          {
            title: '批次分配',
            dataIndex: 'fifo_lot_allocations',
            render: (v: Array<{ lot_no: string; qty: number }> | null) =>
              v?.length ? (
                <span className="font-mono text-[12px]">
                  {v.map((a) => `${a.lot_no}×${formatQty(a.qty)}`).join(' + ')}
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

function IssueModal({
  requisition,
  onClose,
}: {
  requisition: HardwareRequisitionRecord | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)
  const [receivedBy, setReceivedBy] = useState('')
  const [allocations, setAllocations] = useState<Record<string, number>>({})

  useEffect(() => {
    if (requisition) {
      setReceivedBy(requisition.applicant)
      setAllocations(
        Object.fromEntries(requisition.items.map((i) => [i.id, i.need_qty as number])),
      )
    }
  }, [requisition])

  const materialIds = requisition?.items.map((i) => i.material_id) ?? []
  const { data: stockByMaterial } = useQuery({
    queryKey: ['warehouse', 'hardware', 'issue-lots', materialIds.join(',')],
    queryFn: async () => {
      const entries = await Promise.all(
        materialIds.map(async (mid) => {
          const detail = await fetchHardwareStockDetailClient(mid)
          return [mid, detail.lots] as const
        }),
      )
      return Object.fromEntries(entries)
    },
    enabled: materialIds.length > 0 && !!requisition,
  })

  if (!requisition) return null

  const onSubmit = async () => {
    setSubmitting(true)
    try {
      await issueHardwareRequisitionClient(requisition.id, {
        issued_by: 'web',
        received_by: receivedBy,
        items: requisition.items.map((i) => ({
          item_id: i.id,
          issued_qty: allocations[i.id] ?? Number(i.need_qty),
        })),
      })
      message.success('发料完成，库存已扣减并记录流水')
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'stock'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '发料失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`发料确认 · ${requisition.req_no}`}
      open={!!requisition}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="确认发料（实扣）"
      width={700}
    >
      <Table
        size="small"
        rowKey="id"
        dataSource={requisition.items}
        pagination={false}
        columns={[
          { title: '物料', dataIndex: 'material_name', width: 180 },
          { title: '规格', dataIndex: 'spec', width: 110, render: (v) => v || '-' },
          { title: '需求数', dataIndex: 'need_qty', width: 90, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
          {
            title: '建议批次',
            width: 220,
            render: (_: unknown, r) => {
              const lots = stockByMaterial?.[r.material_id] ?? []
              const usable = lots.filter((l) => l.remaining_quantity > 0)
              if (!usable.length) return <StatusTag tone="danger" label="无可用批次" />
              return (
                <span className="text-[12px] font-mono">
                  {usable
                    .slice(0, 3)
                    .map((l) => `${l.lot_no}(${formatQty(l.remaining_quantity)})`)
                    .join(' → ')}
                </span>
              )
            },
          },
          {
            title: '实发量',
            width: 130,
            render: (_: unknown, r) => (
              <InputNumber
                size="small"
                min={1}
                precision={0}
                value={allocations[r.id]}
                onChange={(v) =>
                  setAllocations((prev) => ({ ...prev, [r.id]: v ?? Number(r.need_qty) }))
                }
              />
            ),
          },
        ]}
      />
      <div className="mt-3">
        <div className="mb-1 text-[13px] text-gray-600">领用人点收（=系统签收）</div>
        <Input
          placeholder="领用人姓名"
          value={receivedBy}
          onChange={(e) => setReceivedBy(e.target.value)}
        />
      </div>
    </Modal>
  )
}

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
        size="middle"
        rowKey={(r) => r[0]}
        dataSource={monthly}
        pagination={false}
        columns={[
          { title: '物料', dataIndex: 0 },
          { title: '本月领用量', render: (_: unknown, r) => <span className="tabular-nums">{formatQty(r[1].qty)}</span> },
          { title: '单位', render: (_: unknown, r) => r[1].unit },
          { title: '领用次数', render: (_: unknown, r) => <span className="tabular-nums">{r[1].count}</span> },
        ]}
      />
    </SectionCard>
  )
}
