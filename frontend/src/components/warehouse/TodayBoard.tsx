'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
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
import { DataTable } from './DataTable'

const STATUS_META: Record<PlanStatus, { label: string; color: string }> = {
  planned: { label: '待执行', color: 'gold' },
  in_progress: { label: '执行中', color: 'processing' },
  completed: { label: '已完成', color: 'green' },
  cancelled: { label: '已取消', color: 'default' },
}

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
  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <div>
          <div style={{ fontWeight: 600 }}>
            {plan.material_name} × {plan.quantity} {plan.location_name}
          </div>
          <div style={{ fontSize: 12, color: 'var(--ant-color-text-secondary, #999)' }}>
            {plan.plan_no} · {MOVEMENT_SOURCE_LABEL[plan.source_type as keyof typeof MOVEMENT_SOURCE_LABEL] ?? plan.source_type}
            {plan.planned_date ? ` · 预计 ${dayjs(plan.planned_date).format('MM-DD')}` : ''}
          </div>
          {plan.status === 'cancelled' && plan.cancel_reason && (
            <div style={{ fontSize: 12, color: '#cf4444' }}>原因：{plan.cancel_reason}</div>
          )}
        </div>
        <Tag color={meta.color}>{meta.label}</Tag>
      </div>
      {(plan.status === 'planned' || plan.status === 'in_progress') && (
        <div style={{ marginTop: 8, textAlign: 'right' }}>
          <Space>
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
            <Button size="small" danger onClick={() => onCancel(plan)}>
              取消
            </Button>
          </Space>
        </div>
      )}
    </Card>
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

  const doneColumns = [
    { title: '单号', dataIndex: 'plan_no', width: 160 },
    {
      title: '方向',
      dataIndex: 'direction',
      width: 70,
      render: (v: PlanDirection) => (v === 'inbound' ? <Tag color="green">入</Tag> : <Tag color="red">出</Tag>),
    },
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' as const },
    { title: '库位', dataIndex: 'location_name', width: 110 },
  ]

  return (
    <div>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small" title={`今日待收（${waitingInbound.length + workingIn.length}）`} loading={loadingPlanned}>
            {(waitingInbound.length + workingIn.length) === 0 && (
              <div style={{ color: 'var(--ant-color-text-secondary, #999)' }}>暂无待收计划</div>
            )}
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
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title={`今日待发（${waitingOutbound.length + workingOut.length}）`} loading={loadingInProgress}>
            {(waitingOutbound.length + workingOut.length) === 0 && (
              <div style={{ color: 'var(--ant-color-text-secondary, #999)' }}>暂无待发计划</div>
            )}
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
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="已完成（最近）" loading={loadingDone}>
            <DataTable
              columns={doneColumns}
              dataSource={doneRows}
              pageSize={10}
              page={1}
              total={doneRows.length}
              scrollX={520}
            />
          </Card>
        </Col>
      </Row>

      <Button
        type="primary"
        icon={<PlusOutlined />}
        style={{ marginTop: 12 }}
        onClick={() => setCreateOpen(true)}
      >
        新建计划单
      </Button>

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
        <div style={{ color: 'var(--ant-color-text-secondary, #666)', paddingTop: 8 }}>
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
            <div style={{ marginBottom: 8, color: 'var(--ant-color-text-secondary, #666)' }}>
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
