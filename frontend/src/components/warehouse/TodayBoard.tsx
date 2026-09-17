'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
} from 'antd'
import { ArrowDownLeft, ArrowUpRight, CheckCircle2, Plus } from 'lucide-react'
import dayjs, { type Dayjs } from 'dayjs'
import {
  MOVEMENT_DIRECTION_LABEL,
  MOVEMENT_SOURCE_LABEL,
  type MovementPlanRecord,
  type PlanDirection,
  type PlanStatus,
} from '@/types/warehouse'
import {
  fetchLocationsClient,
  fetchMaterialsClient,
  fetchPlansClient,
} from '@/lib/api/warehouse'
import {
  cancelMovementPlan,
  createMovementPlan,
  generatePlanMovementAction,
  startMovementPlan,
} from '@/actions/warehouse'
import { PageHeader } from './PageHeader'
import { EmptyGuide } from './ui/EmptyGuide'
import { StatusTag } from './ui/StatusTag'
import type { Tone } from './ui/tokens'

const STATUS_META: Record<PlanStatus, { label: string; tone: Tone }> = {
  planned: { label: '待执行', tone: 'warn' },
  in_progress: { label: '执行中', tone: 'info' },
  completed: { label: '已完成', tone: 'ok' },
  cancelled: { label: '已取消', tone: 'default' },
}

/** 泳道计划卡：方向色条 + 单号 + 物料数量主行 + 底部操作 */
function PlanCard({
  plan,
  onStart,
  onGenerate,
  onCancel,
}: {
  plan: MovementPlanRecord
  onStart: (plan: MovementPlanRecord) => void
  onGenerate: (plan: MovementPlanRecord) => void
  onCancel: (plan: MovementPlanRecord) => void
}) {
  const meta = STATUS_META[plan.status]
  const inbound = plan.direction === 'inbound'
  return (
    <div
      className="rounded-lg border border-[var(--color-hairline)] bg-white p-3"
      style={{
        borderLeft: `3px solid ${inbound ? 'var(--wh-ok)' : 'var(--wh-danger)'}`,
        boxShadow: '0 1px 2px rgba(16,24,40,0.04)',
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[12px] text-[var(--color-steel)]">{plan.plan_no}</span>
        <StatusTag tone={meta.tone} label={meta.label} />
      </div>
      <div className="mt-1.5 text-[14px] font-semibold text-[var(--color-charcoal)]">
        {plan.material_name}
        <span className="ml-2 font-normal tabular-nums text-[var(--color-slate)]">
          × {plan.quantity}
        </span>
      </div>
      <div className="mt-1 text-[12px] leading-5 text-[var(--color-steel)]">
        {MOVEMENT_SOURCE_LABEL[plan.source_type as keyof typeof MOVEMENT_SOURCE_LABEL] ?? plan.source_type}
        {plan.planned_date ? ` · 预计 ${dayjs(plan.planned_date).format('MM-DD')}` : ''}
        {plan.location_name ? ` · ${plan.location_name}` : ''}
      </div>
      {plan.status === 'cancelled' && plan.cancel_reason && (
        <div className="mt-1 text-[12px]" style={{ color: 'var(--wh-danger)' }}>
          原因：{plan.cancel_reason}
        </div>
      )}
      {(plan.status === 'planned' || plan.status === 'in_progress') && (
        <div className="mt-2.5 flex justify-end gap-2 border-t border-[var(--color-hairline-soft)] pt-2.5">
          {plan.status === 'planned' && (
            <Button size="small" type="primary" onClick={() => onStart(plan)}>
              开始执行
            </Button>
          )}
          {plan.status === 'in_progress' && (
            <Button size="small" type="primary" onClick={() => onGenerate(plan)}>
              生成登记
            </Button>
          )}
          <Button size="small" onClick={() => onCancel(plan)}>
            取消
          </Button>
        </div>
      )}
    </div>
  )
}

/** 泳道列：标题（图标+名称+计数徽标）+ 卡片流 + 空态引导 */
function Swimlane({
  icon,
  title,
  tone,
  count,
  loading,
  emptyText,
  children,
}: {
  icon: React.ReactNode
  title: string
  tone: Tone
  count: number
  loading: boolean
  emptyText: string
  children: React.ReactNode
}) {
  return (
    <Col xs={24} md={8} className="flex">
      <section
        className="flex min-h-[320px] w-full flex-col rounded-xl border border-[var(--color-hairline)] bg-[var(--color-surface-soft)]"
        style={{ boxShadow: '0 1px 2px rgba(16,24,40,0.04)' }}
      >
        <header className="flex items-center gap-2 border-b border-[var(--color-hairline-soft)] px-4 py-3">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-md [&_svg]:h-[14px] [&_svg]:w-[14px]"
            style={{
              background: tone === 'ok' ? 'var(--wh-ok-bg)' : tone === 'danger' ? 'var(--wh-danger-bg)' : 'var(--color-surface)',
              color: tone === 'ok' ? 'var(--wh-ok)' : tone === 'danger' ? 'var(--wh-danger)' : 'var(--color-steel)',
            }}
          >
            {icon}
          </span>
          <span className="text-[14px] font-semibold text-[var(--color-charcoal)]">{title}</span>
          <span
            className="ml-1 rounded-full px-2 py-0.5 text-[12px] font-medium tabular-nums"
            style={{ background: 'var(--color-surface)', color: 'var(--color-slate)' }}
          >
            {count}
          </span>
        </header>
        <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto p-3">
          {loading ? (
            <div className="py-8 text-center text-[13px] text-[var(--color-stone)]">加载中…</div>
          ) : count === 0 ? (
            <EmptyGuide compact title={emptyText} />
          ) : (
            children
          )}
        </div>
      </section>
    </Col>
  )
}

export function TodayBoard() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [cancelling, setCancelling] = useState<MovementPlanRecord | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  const [generating, setGenerating] = useState<MovementPlanRecord | null>(null)
  const [genQuantity, setGenQuantity] = useState<number | null>(null)
  const [genRemark, setGenRemark] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)

  const { data: planned, isLoading: loadingPlanned } = useQuery({
    queryKey: ['warehouse', 'plans', { status: 'planned', planned_before: today }],
    queryFn: () =>
      fetchPlansClient({ status: 'planned', planned_before: today, page: 1, page_size: 200 }),
  })
  const { data: startedIn, isLoading: loadingInProgress } = useQuery({
    queryKey: ['warehouse', 'plans', { status: 'in_progress', planned_before: today }],
    queryFn: () =>
      fetchPlansClient({ status: 'in_progress', planned_before: today, page: 1, page_size: 50 }),
  })
  const { data: done, isLoading: loadingDone } = useQuery({
    queryKey: ['warehouse', 'plans', { status: 'completed' }],
    queryFn: () => fetchPlansClient({ status: 'completed', page: 1, page_size: 20 }),
  })
  const { data: locations } = useQuery({
    queryKey: ['warehouse', 'locations'],
    queryFn: () => fetchLocationsClient(),
  })

  const invalidateBoards = () => {
    queryClient.invalidateQueries({ queryKey: ['warehouse', 'plans'] })
  }

  const startMutation = useMutation({
    mutationFn: (plan: MovementPlanRecord) => startMovementPlan(plan.id),
    onSuccess: data => {
      message.success(`计划 ${data.plan_no} 已开始执行`)
      invalidateBoards()
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const generateMutation = useMutation({
    mutationFn: (input: { plan: MovementPlanRecord; quantity?: number; remark?: string | null }) =>
      generatePlanMovementAction(input.plan.id, { quantity: input.quantity, remark: input.remark }),
    onSuccess: data => {
      message.success(`已生成登记 ${data.movement.movement_no}，库存已更新`)
      setGenerating(null)
      invalidateBoards()
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (input: { plan: MovementPlanRecord; reason: string }) =>
      cancelMovementPlan(input.plan.id, input.reason),
    onSuccess: () => {
      message.success('计划已取消')
      setCancelling(null)
      invalidateBoards()
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const waitingInbound = (planned?.items ?? []).filter(p => p.direction === 'inbound')
  const workingIn = (startedIn?.items ?? []).filter(p => p.direction === 'inbound')
  const waitingOutbound = (planned?.items ?? []).filter(p => p.direction === 'outbound')
  const workingOut = (startedIn?.items ?? []).filter(p => p.direction === 'outbound')
  const doneRows = done?.items ?? []

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '作业看板']}
        title="作业看板"
        description="今日待收、待发与已完成的出入库计划"
        actions={
          <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
            新建计划单
          </Button>
        }
      />

      <Row gutter={[12, 12]}>
        <Swimlane
          icon={<ArrowDownLeft />}
          title="今日待收"
          tone="ok"
          count={waitingInbound.length + workingIn.length}
          loading={loadingPlanned || loadingInProgress}
          emptyText="今日暂无待收计划"
        >
          {[...waitingInbound, ...workingIn].map(plan => (
            <PlanCard
              key={plan.id}
              plan={plan}
              onStart={p => startMutation.mutate(p)}
              onGenerate={p => {
                setGenerating(p)
                setGenQuantity(p.quantity)
                setGenRemark(p.remark ?? null)
              }}
              onCancel={p => {
                setCancelling(p)
                setCancelReason('')
              }}
            />
          ))}
        </Swimlane>
        <Swimlane
          icon={<ArrowUpRight />}
          title="今日待发"
          tone="danger"
          count={waitingOutbound.length + workingOut.length}
          loading={loadingPlanned || loadingInProgress}
          emptyText="今日暂无待发计划"
        >
          {[...waitingOutbound, ...workingOut].map(plan => (
            <PlanCard
              key={plan.id}
              plan={plan}
              onStart={p => startMutation.mutate(p)}
              onGenerate={p => {
                setGenerating(p)
                setGenQuantity(p.quantity)
                setGenRemark(p.remark ?? null)
              }}
              onCancel={p => {
                setCancelling(p)
                setCancelReason('')
              }}
            />
          ))}
        </Swimlane>
        <Swimlane
          icon={<CheckCircle2 />}
          title="已完成（最近）"
          tone="default"
          count={doneRows.length}
          loading={loadingDone}
          emptyText="暂无已完成计划"
        >
          {doneRows.map(plan => (
            <PlanCard key={plan.id} plan={plan} onStart={() => {}} onGenerate={() => {}} onCancel={() => {}} />
          ))}
        </Swimlane>
      </Row>

      {createOpen && (
        <PlanCreateModal
          locations={locations ?? []}
          onClose={() => setCreateOpen(false)}
        />
      )}

      <Modal
        title={`取消计划 ${cancelling?.plan_no ?? ''}`}
        open={!!cancelling}
        confirmLoading={cancelMutation.isPending}
        onOk={() => {
          const reason = cancelReason.trim()
          if (!reason) {
            message.error('请填写取消原因')
            return
          }
          if (cancelling) cancelMutation.mutate({ plan: cancelling, reason })
        }}
        onCancel={() => setCancelling(null)}
        destroyOnHidden
      >
        <div style={{ color: 'var(--color-steel)', paddingTop: 8 }}>
          取消后计划单不可恢复，请填写取消原因（必填）。
        </div>
        <Input
          value={cancelReason}
          onChange={e => setCancelReason(e.target.value)}
          placeholder="如：到货延期 / 生产计划变更"
          style={{ marginTop: 8 }}
        />
      </Modal>

      <Modal
        title={`生成登记：${generating?.plan_no ?? ''}`}
        open={!!generating}
        confirmLoading={generateMutation.isPending}
        onOk={() => {
          if (!generating) return
          if (!genQuantity || genQuantity <= 0) {
            message.error('请输入大于 0 的数量')
            return
          }
          generateMutation.mutate({ plan: generating, quantity: genQuantity, remark: genRemark })
        }}
        onCancel={() => setGenerating(null)}
        destroyOnHidden
      >
        {generating && (
          <div style={{ paddingTop: 8 }}>
            <div style={{ marginBottom: 8, color: 'var(--color-steel)' }}>
              {generating.direction === 'inbound' ? '入库登记' : '出库登记'} ·{' '}
              {generating.material_name} · {generating.location_name}
            </div>
            <div style={{ marginBottom: 8 }}>
              数量：
              <InputNumber
                min={0.0001}
                value={genQuantity}
                onChange={v => setGenQuantity(v)}
                style={{ width: 160, marginLeft: 8 }}
              />
            </div>
            <Input
              value={genRemark ?? ''}
              onChange={e => setGenRemark(e.target.value)}
              placeholder="备注（可空）"
            />
          </div>
        )}
      </Modal>
    </div>
  )
}

function PlanCreateModal({
  locations,
  onClose,
}: {
  locations: { id: string; code: string; name: string }[]
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [materialOptions, setMaterialOptions] = useState<{ value: string; label: string }[]>([])
  const [direction, setDirection] = useState<PlanDirection>('inbound')
  const [form] = Form.useForm()

  const searchMaterials = async (keyword: string) => {
    const res = await fetchMaterialsClient({ page: 1, page_size: 50, keyword: keyword || undefined })
    setMaterialOptions(res.items.map(m => ({ value: m.id, label: `${m.code} ${m.name}` })))
  }

  const createMutation = useMutation({
    mutationFn: (values: { direction: PlanDirection; source_type: string; material_id: string; batch_no?: string; quantity: number; location_id: string; planned_date?: Dayjs | null; remark?: string }) =>
      createMovementPlan({
        direction: values.direction,
        source_type: values.source_type,
        material_id: values.material_id,
        batch_no: values.batch_no ?? '',
        quantity: values.quantity,
        location_id: values.location_id,
        planned_date: values.planned_date ? (values.planned_date as Dayjs).format('YYYY-MM-DD') : null,
        remark: values.remark || null,
      }),
    onSuccess: record => {
      message.success(`计划单 ${record.plan_no} 已创建`)
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'plans'] })
      onClose()
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  return (
    <Modal
      title="新建计划单"
      open
      confirmLoading={saving}
      onOk={async () => {
        const values = await form.validateFields()
        setSaving(true)
        createMutation.mutate(values, { onSettled: () => setSaving(false) })
      }}
      onCancel={onClose}
      destroyOnHidden
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        style={{ paddingTop: 8 }}
        initialValues={{ direction: 'inbound', source_type: 'purchase' }}
      >
        <Space.Compact block>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]} style={{ width: 140 }}>
            <Select
              onChange={v => setDirection(v)}
              options={[
                { value: 'inbound', label: '入库' },
                { value: 'outbound', label: '出库' },
              ]}
            />
          </Form.Item>
          <Form.Item name="source_type" label="业务来源" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select
              options={Object.entries(MOVEMENT_SOURCE_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="material_id" label="物料" rules={[{ required: true, message: '请选择物料' }]}>
          <Select
            showSearch
            filterOption={false}
            onSearch={searchMaterials}
            placeholder="输入编码或名称搜索"
            options={materialOptions}
          />
        </Form.Item>
        <Space.Compact block>
          <Form.Item name="batch_no" label="批次号（可空）" style={{ width: 180 }}>
            <Input />
          </Form.Item>
          <Form.Item name="quantity" label="计划数量" rules={[{ required: true, message: '请输入数量' }]} style={{ flex: 1 }}>
            <InputNumber min={0.0001} style={{ width: '100%' }} />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="location_id" label="库位" rules={[{ required: true, message: '请选择库位' }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={locations.map(loc => ({ value: loc.id, label: `${loc.code} ${loc.name}` }))}
          />
        </Form.Item>
        <Form.Item name="planned_date" label="预计日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
