'use client'

import { useState, useMemo, useRef, useEffect } from 'react'
import {
  App,
  Button,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { usePermission } from '@/hooks/usePermission'
import { fetchPlanOrderClient } from '@/lib/api/production-client'
import {
  updatePlanOrder,
  confirmPlanOrder,
  closePlanOrder,
  deletePlanOrder,
  changePlanOrder,
} from '@/actions/production'
import { StageConfigItem, type PlanOrderDetail, type PlanItem, type PlanItemBatchProgress, type PlanOrderChangeItem } from '@/types/production'
import { batchGenDayOffset, batchRhythmWarning } from './utils'
import { fetchProductsClient, fetchRoutesClient, fetchRouteGraphClient } from '@/lib/api/production-client'
import dayjs from 'dayjs'
import { PlanItemTable, StageProgressBar } from './PlanItemTable'
import { ReleaseConfirmModal } from './ReleaseConfirmModal'
import { STATUS_CONFIG, STATUS_THEME, PRIORITY_CONFIG, STAGE_PRESET_COLORS } from './constants'
import { decrementBatchNo, incrementBatchNo } from '@/lib/utils'
import { DownOutlined, RightOutlined } from '@ant-design/icons'

const { Text } = Typography

// ── Sub-components ──

function InlineEditForm({ form, onSave, onCancel, products, routes, onProductChange }: {
  form: FormInstance
  onSave: () => Promise<void>
  onCancel: () => void
  products: { id: string; product_name: string }[]
  routes: { id: string; route_name: string }[]
  onProductChange: (productId: string) => void
}) {
  const productId = Form.useWatch('product_id', form)
  return (
    <Form form={form} layout="vertical" style={{ animation: 'fadeIn 0.2s ease' }}>
      <Form.Item name="title" label="标题" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <div style={{ display: 'flex', gap: 12 }}>
        <Form.Item name="product_id" label="产品" style={{ flex: 1 }} rules={[{ required: true }]}>
          <Select
            showSearch
            placeholder="选择产品"
            filterOption={(input, option) => (option?.label as string)?.toLowerCase().includes(input.toLowerCase())}
            onChange={(id: string) => { onProductChange(id); form.setFieldValue('route_id', undefined) }}
            options={products.map((p) => ({ value: p.id, label: p.product_name }))}
          />
        </Form.Item>
        <Form.Item name="route_id" label="工艺路线" style={{ flex: 1 }} rules={[{ required: true }]}>
          <Select
            placeholder="先选产品"
            disabled={!productId}
            options={routes.map((r) => ({ value: r.id, label: `${r.route_name}` }))}
          />
        </Form.Item>
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <Form.Item name="scheduled_start" label="开始日期" style={{ flex: 1 }}>
          <Input type="date" />
        </Form.Item>
        <Form.Item name="scheduled_end" label="结束日期" style={{ flex: 1 }}>
          <Input type="date" />
        </Form.Item>
        <Form.Item name="priority" label="优先级" style={{ flex: 1 }}>
          <Select
            options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
          />
        </Form.Item>
      </div>
      <Form.Item name="remark" label="备注">
        <Input.TextArea rows={2} />
      </Form.Item>
      <Space>
        <Button type="primary" onClick={onSave}>保存</Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </Form>
  )
}

function DetailView({ order, productName, routeName, formatDate }: {
  order: PlanOrderDetail
  productName: string | null
  routeName: string | null
  formatDate: (d: string | null) => string
}) {
  const leftFields = [
    { label: '标题', value: order.title },
    { label: '产品', value: productName ?? '—' },
    { label: '工艺路线', value: routeName ?? '—' },
  ]
  const rightFields = [
    { label: '计划周期', value: `${formatDate(order.scheduled_start)} ~ ${formatDate(order.scheduled_end)}` },
    { label: '优先级', value: (PRIORITY_CONFIG[order.priority] ?? { label: order.priority }).label },
    { label: '版本', value: `v${order.plan_version}` },
  ]

  return (
    <div>
      {/* Two-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 32px' }}>
        <div>
          {leftFields.map((f) => (
            <div key={f.label} style={detailRow}>
              <span style={detailLabel}>{f.label}</span>
              <span style={detailValue}>{f.value}</span>
            </div>
          ))}
        </div>
        <div>
          {rightFields.map((f) => (
            <div key={f.label} style={detailRow}>
              <span style={detailLabel}>{f.label}</span>
              <span style={detailValue}>{f.value}</span>
            </div>
          ))}
        </div>
      </div>
      {/* Remark: full-width below */}
      {order.remark && (
        <div style={{ ...detailRow, borderBottom: 'none' }}>
          <span style={detailLabel}>备注</span>
          <span style={{ ...detailValue, color: 'var(--color-steel)', fontSize: 13 }}>{order.remark}</span>
        </div>
      )}
    </div>
  )
}

const detailRow: React.CSSProperties = {
  display: 'flex', padding: '6px 0',
  borderBottom: '1px solid var(--color-hairline-soft)',
}
const detailLabel: React.CSSProperties = {
  width: 80, flexShrink: 0, fontSize: 13, color: 'var(--color-slate)',
}
const detailValue: React.CSSProperties = {
  fontSize: 14, color: 'var(--color-charcoal)',
}

// ── Compact demand chips ──

function DemandSection({ allocations }: { allocations: PlanOrderDetail['demand_allocations'] }) {
  if (!allocations?.length) {
    return <Empty description="暂无关联需求" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {allocations.map((a) => (
        <div key={a.id} style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: 'var(--color-surface-soft)',
          borderRadius: 6,
          padding: '5px 10px',
          fontSize: 13,
        }}>
          <span style={{ fontWeight: 500, color: 'var(--color-charcoal)' }}>{a.demand_no ?? '—'}</span>
          <span style={{ color: 'var(--color-hairline-strong)' }}>·</span>
          <span style={{ color: 'var(--color-slate)' }}>{a.intermediate_type_name ?? '—'}</span>
          <span style={{ color: 'var(--color-hairline-strong)' }}>·</span>
          <span style={{ color: 'var(--color-slate)' }}>{a.allocated_quantity}</span>
          <span style={{ color: 'var(--color-stone)', fontSize: 12 }}>#{a.item_no}</span>
        </div>
      ))}
    </div>
  )
}

// ── Section header with status accent ──

function SectionHead({ label, count, accentColor, collapsed, onToggle }: {
  label: string; count?: number; accentColor: string
  collapsed?: boolean; onToggle?: () => void
}) {
  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, cursor: onToggle ? 'pointer' : undefined }}
      onClick={onToggle}
    >
      <span style={{
        width: 3, height: 16, borderRadius: 2,
        backgroundColor: accentColor,
        display: 'inline-block', flexShrink: 0,
      }} />
      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-slate)' }}>
        {label}{count != null ? ` (${count})` : ''}
      </span>
      {onToggle && (
        <span style={{ marginLeft: 'auto', color: 'var(--color-steel)', fontSize: 11 }}>
          {collapsed ? <RightOutlined /> : <DownOutlined />}
        </span>
      )}
    </div>
  )
}

// ── Section divider ──

const sectionDivider: React.CSSProperties = {
  height: 1,
  background: 'var(--color-hairline)',
  margin: '22px 0',
}

// ── Main ──

interface Props {
  orderId: string | null
  onClose: () => void
  changeReason?: string
}

export function PlanOrderDetailDrawer({ orderId, onClose, changeReason }: Props) {
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:planning:submit')
  const { modal, message } = App.useApp()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editForm] = Form.useForm()
  const [releaseModalOpen, setReleaseModalOpen] = useState(false)
  const [stageEditOpen, setStageEditOpen] = useState(false)
  const [stageEditForm, setStageEditForm] = useState<StageConfigItem[]>([])
  const [editProductId, setEditProductId] = useState<string | undefined>()

  const { data: order, isLoading } = useQuery({
    queryKey: ['plan-order-detail', orderId],
    queryFn: () => fetchPlanOrderClient(orderId!),
    enabled: !!orderId,
  })

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: ['plan-order-detail', orderId] })
    queryClient.invalidateQueries({ queryKey: ['plan-orders'] })
    queryClient.invalidateQueries({ queryKey: ['scheduleView'] })
  }

  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: () => fetchProductsClient(),
    staleTime: 60_000,
  })

  const { data: routes } = useQuery({
    queryKey: ['routes', order?.product_id],
    queryFn: () => fetchRoutesClient(order!.product_id!),
    enabled: !!order?.product_id,
    staleTime: 60_000,
  })

  // 编辑模式下按选中产品查路线
  const { data: editRoutes } = useQuery({
    queryKey: ['routes', editProductId],
    queryFn: () => fetchRoutesClient(editProductId!, 'published'),
    enabled: !!editProductId,
    staleTime: 60_000,
  })

  // 工段配置：从工艺路线图获取可用工段名
  const { data: routeGraph } = useQuery({
    queryKey: ['routeGraph', order?.route_id],
    queryFn: () => fetchRouteGraphClient(order!.route_id!),
    enabled: !!order?.route_id,
  })

  // 变更模式
  const prevOrderRef = useRef<string | null>(null)
  const [changeMode, setChangeMode] = useState(false)
  const [changeForm] = Form.useForm()
  const [localItems, setLocalItems] = useState<PlanItem[]>([])
  const [deletedItemIds, setDeletedItemIds] = useState<string[]>([])
  const [delayStartItemNo, setDelayStartItemNo] = useState<number | undefined>()
  const [delayDays, setDelayDays] = useState<number>(0)

  // 批量生成计划项
  const [batchGenOpen, setBatchGenOpen] = useState(false)
  const [batchStartNo, setBatchStartNo] = useState('')
  const [batchCount, setBatchCount] = useState(1)
  const [batchIntervalDays, setBatchIntervalDays] = useState(1) // m：每隔 m 天
  const [batchGroupSize, setBatchGroupSize] = useState(1) // n：生成 n 批
  const [batchGapDays, setBatchGapDays] = useState(1) // k：每批间隔 k 天
  const [batchIncludeFirst, setBatchIncludeFirst] = useState(true) // 前一项参与生成：参考项占序列第 1 位，新批次从其后续位置继续

  // 折叠区块
  const [showBasicInfo, setShowBasicInfo] = useState(false)
  const [showDemands, setShowDemands] = useState(false)

  // 变更模式下订单数据到达时自动进入变更模式
  useEffect(() => {
    if (order && changeReason && !changeMode && prevOrderRef.current !== order.id) {
      prevOrderRef.current = order.id
      setChangeMode(true)
      setLocalItems(order.items ? order.items.map(i => ({ ...i })) : [])
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- changeMode guarded by !changeMode
  }, [order, changeReason])

  // drawer 关闭时重置状态，确保再次打开同一计划单可正常进入变更模式
  const handleDrawerClose = () => {
    prevOrderRef.current = null
    setChangeMode(false)
    setDeletedItemIds([])
    onClose()
  }

  const availableStages = useMemo(() => {
    if (!routeGraph?.nodes) return []
    const names = new Set<string>()
    for (const node of routeGraph.nodes) {
      if (node.stage_name) names.add(node.stage_name)
    }
    return [...names]
  }, [routeGraph])

  const productId = order?.product_id
  const productName = useMemo(() => {
    if (!productId || !products) return null
    return products.find((p) => p.id === productId)?.product_name ?? null
  }, [productId, products])

  const routeId = order?.route_id
  const routeName = useMemo(() => {
    if (!routeId || !routes) return null
    const r = routes.find((r) => r.id === routeId)
    return r ? `${r.route_name}` : null
  }, [routeId, routes])

  const status = order ? (STATUS_CONFIG[order.status] ?? { label: order.status, color: 'default' }) : null
  const accentColor = order ? (STATUS_THEME[order.status] ?? STATUS_THEME.draft).bar : 'var(--color-stone)'

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const handleEdit = () => {
    editForm.setFieldsValue({
      title: order?.title,
      product_id: order?.product_id,
      route_id: order?.route_id,
      scheduled_start: order?.scheduled_start ? order.scheduled_start.slice(0, 10) : undefined,
      scheduled_end: order?.scheduled_end ? order.scheduled_end.slice(0, 10) : undefined,
      priority: order?.priority,
      remark: order?.remark,
    })
    setEditProductId(order?.product_id ?? undefined)
    setEditing(true)
  }

  const handleSaveEdit = async () => {
    const values = await editForm.validateFields().catch(() => null)
    if (!values || !orderId) return
    const r = await updatePlanOrder(orderId, values)
    if (r.success) {
      message.success('已保存')
      setEditing(false)
      refetch()
    } else {
      message.error(r.error)
    }
  }

  const handleConfirm = () => {
    if (!orderId) return
    modal.confirm({
      title: `确认计划单「${order?.order_no}」?`,
      content: '确认后将锁定计划项，无法再增删或修改。',
      okText: '确认并锁定',
      cancelText: '取消',
      onOk: async () => {
        const r = await confirmPlanOrder(orderId)
        if (r.success) { message.success('已确认'); refetch() }
        else { message.error(r.error) }
      },
    })
  }

  const handleCloseOrder = () => {
    if (!order) return
    modal.confirm({
      title: `关闭计划单「${order.order_no}」?`,
      content: '关闭后将无法继续操作。',
      okText: '确认关闭',
      cancelText: '取消',
      onOk: async () => {
        const r = await closePlanOrder(order.id)
        if (r.success) { message.success('已关闭'); refetch() }
        else { message.error(r.error) }
      },
    })
  }

  const handleDelete = () => {
    if (!order) return
    modal.confirm({
      title: `删除计划单「${order.order_no}」?`,
      content: '删除后不可恢复。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const r = await deletePlanOrder(order.id)
        if (r.success) {
          message.success('已删除')
          refetch()
          handleDrawerClose()
        } else {
          message.error(r.error)
        }
      },
    })
  }

  const handleOpenStageConfig = () => {
    if (!order) return
    if (order.stage_config && order.stage_config.length > 0) {
      setStageEditForm(order.stage_config.map((s: StageConfigItem) => ({ ...s })))
    } else if (availableStages.length > 0) {
      // 无已有配置时，从工艺路线预填工段列表
      setStageEditForm(availableStages.map((name, i) => ({
        stage_name: name,
        duration_hours: 24,
        color: STAGE_PRESET_COLORS[i % STAGE_PRESET_COLORS.length],
      })))
    } else {
      setStageEditForm([])
    }
    setStageEditOpen(true)
  }

  const updateLocalItem = (id: string, patch: Partial<PlanItem>) => {
    setLocalItems(prev => prev.map(i => i.id === id ? { ...i, ...patch } : i))
  }

  const handleBatchGenerate = () => {
    if (!batchStartNo || batchCount <= 0) return
    if (localItems.length === 0) { message.error('请先添加至少一个计划项'); return }
    // 仅当生成批次足以跨组时组间才可能重叠（不足一组时全部落在同一组内、逐批间隔互不重叠）；
    // 开启"前项参与"时参考项占组内第 1 位，新批次从第 2 位起，故跨组所需批次少一批
    if (batchCount >= batchGroupSize + (batchIncludeFirst ? 0 : 1)) {
      const warn = batchRhythmWarning(batchGroupSize, batchIntervalDays, batchGapDays)
      if (warn) { message.warning(warn); return }
    }
    const lastItem = localItems[localItems.length - 1]
    const lastStart = lastItem.planned_start ? new Date(lastItem.planned_start) : new Date()
    const lastEnd = lastItem.planned_end ? new Date(lastItem.planned_end) : new Date()

    const newItems: PlanItem[] = []
    let currentNo = batchStartNo
    const startBase = lastStart.getTime()
    const endBase = lastEnd.getTime()

    for (let i = 1; i <= batchCount; i++) {
      // 第 i 批：参考项作序列第 0 个（或开启"前一项参与生成"时作第 1 个，新批次从第 2 位继续），
      // 第 i//n 组的起点偏移 i//n*m 天，组内第 i%n 批再间隔 (i%n)*k 天
      const seqIdx = batchIncludeFirst ? i + 1 : i
      const dayOffset = batchGenDayOffset(seqIdx, batchGroupSize, batchIntervalDays, batchGapDays)
      const msOffset = dayOffset * 86400000

      newItems.push({
        id: `_new_${crypto.randomUUID()}`,
        item_no: localItems.length + newItems.length + 1,
        plan_order_id: order!.id,
        product_id: order!.product_id ?? '',
        product_name: order!.items?.[0]?.product_name ?? '',
        route_id: order!.route_id,
        equipment_id: null,
        planned_quantity: null,
        unit: null,
        batch_no: currentNo,
        planned_start: new Date(startBase + msOffset).toISOString(),
        planned_end: new Date(endBase + msOffset).toISOString(),
        status: 'allocated',
        priority: 'medium',
        sort_order: 0,
        remark: null,
        stage_durations: order!.stage_config,
        allocations: [],
        demand_allocations: [],
        created_at: '',
        updated_at: '',
      })
      currentNo = incrementBatchNo(currentNo)
    }
    setLocalItems(prev => [...prev, ...newItems])
    message.success(`已生成 ${batchCount} 个计划项`)
  }

  const handleOpenBatchGen = () => {
    const lastItem = localItems[localItems.length - 1]
    setBatchStartNo(lastItem?.batch_no ? incrementBatchNo(lastItem.batch_no) : '')
    setBatchCount(1)
    setBatchIntervalDays(1)
    setBatchGroupSize(1)
    setBatchGapDays(1)
    setBatchIncludeFirst(true)
    setBatchGenOpen(true)
  }

  const removeItem = (record: PlanItem, shift: boolean) => {
    setLocalItems(prev => {
      const idx = prev.findIndex(i => i.id === record.id && i.item_no === record.item_no)
      let next = prev.filter(i => i.id !== record.id || i.item_no !== record.item_no)
      if (shift && idx >= 0) {
        // 被删行之后的每一行批号数字减 1（时间字段不动）
        next = next.map((i, j) => j >= idx ? { ...i, batch_no: decrementBatchNo(i.batch_no ?? '') || null } : i)
      }
      return next
    })
    if (record.id && !String(record.id).startsWith('_new_')) setDeletedItemIds(prev => [...prev, record.id])
  }

  const handleDeleteItem = (record: PlanItem) => {
    const idx = localItems.findIndex(i => i.id === record.id && i.item_no === record.item_no)
    // 被删行之后、批号数字可减的后续行（用于预览与按钮显隐）
    const following = idx >= 0
      ? localItems.slice(idx + 1).filter(i => i.batch_no && decrementBatchNo(i.batch_no) !== i.batch_no)
      : []
    const label = record.batch_no || `#${record.item_no}`
    const preview = following.slice(0, 5)
      .map(i => `${i.batch_no} → ${decrementBatchNo(i.batch_no!)}`).join('、')

    const ins = modal.confirm({
      title: `删除计划项「${label}」?`,
      content: following.length > 0 ? (
        <div>
          后续 {following.length} 个批号将前移补位：
          <br />
          {preview}{following.length > 5 ? ` …等 ${following.length} 个` : ''}
        </div>
      ) : (
        <div>删除后不可恢复。</div>
      ),
      // footer 三按钮：取消 / 删除 / 删除并顺延
      footer: (_originNode, { CancelBtn }) => (
        <>
          <CancelBtn />
          <Button danger onClick={() => { ins.destroy(); removeItem(record, false) }}>删除</Button>
          {following.length > 0 && (
            <Button danger type="primary" onClick={() => { ins.destroy(); removeItem(record, true) }}>删除并补位</Button>
          )}
        </>
      ),
    })
  }

  const handleSaveChange = async () => {
    if (!orderId) return
    const headerValues = await changeForm.validateFields().catch(() => null)
    if (!headerValues) return

    modal.confirm({
      title: '确认保存变更？',
      content: `将对计划单「${order?.order_no}」执行变更，变更原因：${changeReason}`,
      okText: '确认保存',
      cancelText: '取消',
      onOk: async () => {
        const upsertItems: PlanOrderChangeItem[] = localItems.map(i => {
          const base: PlanOrderChangeItem = {
            product_id: i.product_id,
            product_name: i.product_name,
            route_id: i.route_id || undefined,
            equipment_id: i.equipment_id || undefined,
            planned_quantity: i.planned_quantity ?? undefined,
            unit: i.unit || undefined,
            batch_no: i.batch_no || undefined,
            stage_durations: i.stage_durations || undefined,
            planned_start: i.planned_start || undefined,
            planned_end: i.planned_end || undefined,
            priority: i.priority,
            remark: i.remark || undefined,
            sort_order: i.sort_order,
          }
          if (i.id && !String(i.id).startsWith('_new_')) (base as Record<string, unknown>).id = i.id
          return base
        })

        const r = await changePlanOrder(orderId, {
          change_reason: changeReason!,
          ...headerValues,
          items_upsert: upsertItems,
          items_delete: deletedItemIds.length > 0 ? deletedItemIds : undefined,
        })
        if (r.success) {
          message.success('变更已保存')
          setChangeMode(false)
          setDeletedItemIds([])
          refetch()
        } else {
          message.error(r.error)
        }
      },
    })
  }

  return (
    <Drawer
      title="计划单详情"
      open={!!orderId}
      onClose={handleDrawerClose}
      maskClosable={false}
      size="large"
      destroyOnHidden
      styles={{ body: { padding: 0 } }}
    >
      {isLoading || !order ? (
        <div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>
      ) : (
        <>
          {/* Sticky header — order identity + actions */}
          <div style={{
            position: 'sticky', top: 0, zIndex: 10,
            background: 'var(--color-canvas)',
            padding: '14px 24px',
            borderBottom: '1px solid var(--color-hairline)',
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <span style={{
              width: 10, height: 10, borderRadius: '50%',
              backgroundColor: accentColor,
              display: 'inline-block', flexShrink: 0,
            }} />
            <Text strong style={{ fontSize: 16 }}>{order.order_no}</Text>
            <Tag color={status?.color}>{status?.label}</Tag>
            <Tag>v{order.plan_version}</Tag>
            {order.scheduled_start && (
              <span style={{ fontSize: 13, color: 'var(--color-steel)', marginLeft: 4 }}>
                {formatDate(order.scheduled_start)} ~ {formatDate(order.scheduled_end)}
              </span>
            )}
            {canSubmit && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              {order.status === 'draft' && (
                <>
                  <Button type="primary" size="small" onClick={handleConfirm}>确认并锁定</Button>
                  <Button size="small" onClick={handleEdit}>编辑</Button>
                  <Button size="small" danger onClick={handleDelete}>删除</Button>
                </>
              )}
              {order.status === 'confirmed' && (
                <>
                  <Button size="small" onClick={handleEdit}>编辑</Button>
                  <Button type="primary" size="small" onClick={() => setReleaseModalOpen(true)}>下达</Button>
                  <Button size="small" onClick={handleCloseOrder}>关闭</Button>
                </>
              )}
              {(order.status === 'released' || order.status === 'completed') && (
                <>
                  {changeMode ? (
                    <>
                      <Button type="primary" size="small" onClick={handleSaveChange}>保存变更</Button>
                      <Button size="small" onClick={() => { setChangeMode(false); setDeletedItemIds([]); prevOrderRef.current = null }}>取消</Button>
                    </>
                  ) : (
                    <Button size="small" onClick={handleCloseOrder}>关闭计划单</Button>
                  )}
                </>
              )}
            </div>
            )}
          </div>

          {/* Body — left accent strip + sections */}
          <div style={{ padding: '20px 24px 20px 20px' }}>
            {/* Section: 基本信息 — collapsible, default closed */}
            <SectionHead label="基本信息" accentColor={accentColor} collapsed={!showBasicInfo} onToggle={() => setShowBasicInfo(v => !v)} />
            {showBasicInfo && (
              <>
                {changeMode ? (
                  <Form
                    form={changeForm}
                    layout="vertical"
                    initialValues={{
                      title: order.title,
                      scheduled_start: order.scheduled_start?.slice(0, 10) ?? undefined,
                      scheduled_end: order.scheduled_end?.slice(0, 10) ?? undefined,
                      priority: order.priority,
                      remark: order.remark ?? '',
                    }}
                  >
                    <div style={{ display: 'flex', gap: 12 }}>
                      <Form.Item name="title" label="标题" style={{ flex: 1 }} rules={[{ required: true }]}>
                        <Input />
                      </Form.Item>
                    </div>
                    <div style={{ display: 'flex', gap: 12 }}>
                      <Form.Item name="scheduled_start" label="开始日期" style={{ flex: 1 }}>
                        <Input type="date" />
                      </Form.Item>
                      <Form.Item name="scheduled_end" label="结束日期" style={{ flex: 1 }}>
                        <Input type="date" />
                      </Form.Item>
                      <Form.Item name="priority" label="优先级" style={{ flex: 1 }}>
                        <Select options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))} />
                      </Form.Item>
                    </div>
                    <Form.Item name="remark" label="备注">
                      <Input.TextArea rows={2} />
                    </Form.Item>
                  </Form>
                ) : editing ? (
                  <InlineEditForm
                    form={editForm}
                    onSave={handleSaveEdit}
                    onCancel={() => { setEditing(false); setEditProductId(undefined) }}
                    products={products ?? []}
                    routes={editRoutes ?? []}
                    onProductChange={setEditProductId}
                  />
                ) : (
                  <DetailView order={order} productName={productName} routeName={routeName} formatDate={formatDate} />
                )}
              </>
            )}

            <div style={sectionDivider} />

            {/* Section: 计划项 */}
            <SectionHead label="计划项" count={changeMode ? localItems.length : (order.items?.length ?? 0)} accentColor={accentColor} />
            {changeMode ? (
              <div>
                {localItems.length > 0 && (
                  <Space style={{ marginBottom: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>快捷顺延：从</span>
                    <Select
                      size="small"
                      placeholder="选择起始项"
                      style={{ width: 120 }}
                      value={delayStartItemNo}
                      onChange={setDelayStartItemNo}
                      options={localItems
                        .filter(i => !!i.id)
                        .sort((a, b) => a.item_no - b.item_no)
                        .map(i => ({ value: i.item_no, label: `${i.batch_no || `#${i.item_no}`}` }))}
                    />
                    <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>往后顺延</span>
                    <InputNumber size="small" min={0} step={1} value={delayDays} onChange={v => setDelayDays(v ?? 0)} style={{ width: 70 }} />
                    <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>天</span>
                    {canSubmit && (
                    <Button
                      size="small"
                      onClick={() => {
                        if (!delayStartItemNo || delayDays <= 0) return
                        const msPerDay = delayDays * 86400000
                        setLocalItems(prev => prev.map(i => {
                          if (i.item_no < delayStartItemNo) return i
                          const patch: Partial<PlanItem> = {}
                          if (i.planned_start) patch.planned_start = new Date(new Date(i.planned_start).getTime() + msPerDay).toISOString()
                          if (i.planned_end) patch.planned_end = new Date(new Date(i.planned_end).getTime() + msPerDay).toISOString()
                          return { ...i, ...patch }
                        }))
                        message.success(`已顺延 ${delayDays} 天`)
                      }}
                      disabled={!delayStartItemNo || delayDays <= 0}
                    >顺延</Button>
                    )}
                  </Space>
                )}
                <Table
                  dataSource={localItems}
                  rowKey={(record) => record.id || `new-${record.item_no}`}
                  size="small"
                  pagination={false}
                  scroll={{ x: 850 }}
                  columns={[
                    { title: '序号', dataIndex: 'item_no', width: 55 },
                    {
                      title: '批号',
                      dataIndex: 'batch_no',
                      width: 145,
                      render: (v: string | null, record: PlanItem) => (
                        <Input
                          size="small"
                          value={v ?? ''}
                          style={{ width: 120, fontWeight: 600 }}
                          onChange={e => updateLocalItem(record.id, { batch_no: e.target.value || undefined })}
                        />
                      ),
                    },
                    {
                      title: '数量',
                      dataIndex: 'planned_quantity',
                      width: 90,
                      render: (v: number | null, record: PlanItem) => (
                        <InputNumber
                          size="small"
                          value={v}
                          min={0}
                          style={{ width: 72 }}
                          onChange={val => updateLocalItem(record.id, { planned_quantity: val ?? undefined })}
                        />
                      ),
                    },
                    {
                      title: '开始时间',
                      dataIndex: 'planned_start',
                      width: 160,
                      render: (v: string | null, record: PlanItem) => (
                        <DatePicker
                          showTime
                          format="YYYY-MM-DD HH:mm"
                          size="small"
                          style={{ width: 140 }}
                          value={v ? dayjs(v) : null}
                          onChange={d => updateLocalItem(record.id, { planned_start: d ? d.toISOString() : undefined })}
                        />
                      ),
                    },
                    {
                      title: '结束时间',
                      dataIndex: 'planned_end',
                      width: 160,
                      render: (v: string | null, record: PlanItem) => (
                        <DatePicker
                          showTime
                          format="YYYY-MM-DD HH:mm"
                          size="small"
                          style={{ width: 140 }}
                          value={v ? dayjs(v) : null}
                          onChange={d => updateLocalItem(record.id, { planned_end: d ? d.toISOString() : undefined })}
                        />
                      ),
                    },
                    {
                      title: '工序进度',
                      dataIndex: 'batch_progress',
                      width: 180,
                      render: (bp: PlanItemBatchProgress | null, record: PlanItem) => (
                        <StageProgressBar
                          stageDurations={record.stage_durations}
                          batchProgress={bp}
                        />
                      ),
                    },
                    {
                      title: '操作',
                      width: 60,
                      render: (_: unknown, record: PlanItem) => (
                        canSubmit ? <Button type="text" size="small" danger onClick={() => handleDeleteItem(record)}>删除</Button> : null
                      ),
                    },
                  ]}
                />
                <div style={{ marginTop: 10, padding: '8px 10px', background: 'var(--color-surface-soft)', borderRadius: 6 }}>
                  {batchGenOpen ? (
                    <Space wrap size="small">
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>起始批号</span>
                      <Input size="small" placeholder="自动取最后项递增" value={batchStartNo} onChange={e => setBatchStartNo(e.target.value)} style={{ width: 130 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>数量</span>
                      <InputNumber size="small" min={1} value={batchCount} onChange={v => setBatchCount(v ?? 1)} style={{ width: 60 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>每</span>
                      <InputNumber size="small" min={1} value={batchIntervalDays} onChange={v => setBatchIntervalDays(v ?? 1)} style={{ width: 50 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>天生成</span>
                      <InputNumber size="small" min={1} value={batchGroupSize} onChange={v => setBatchGroupSize(v ?? 1)} style={{ width: 50 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>批，批间隔</span>
                      <InputNumber size="small" min={0} value={batchGapDays} onChange={v => setBatchGapDays(v ?? 0)} style={{ width: 50 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>天</span>
                      <Tooltip title="开启后最后一项计入序列，新批次从其后一位继续；关闭则与最后一项同日排入">
                        <span style={{ fontSize: 12, color: 'var(--color-slate)' }}>前项参与</span>
                        <Switch size="small" checked={batchIncludeFirst} onChange={setBatchIncludeFirst} />
                      </Tooltip>
                      <Button size="small" type="primary" onClick={handleBatchGenerate} disabled={!batchStartNo}>生成</Button>
                      <Button size="small" onClick={() => setBatchGenOpen(false)}>收起</Button>
                    </Space>
                  ) : (
                    <Button size="small" type="link" disabled={localItems.length === 0} onClick={handleOpenBatchGen}>
                      + 批量生成
                    </Button>
                  )}
                </div>
                {canSubmit && (
                <Button
                  type="dashed" size="small" style={{ marginTop: 8 }}
                  onClick={() => {
                    const newItem: PlanItem = {
                      id: `_new_${crypto.randomUUID()}`, item_no: (localItems.length + 1), plan_order_id: order!.id,
                      product_id: order!.product_id ?? '', product_name: order!.items?.[0]?.product_name ?? '',
                      route_id: order!.route_id, equipment_id: null,
                      planned_quantity: null, unit: null, batch_no: '',
                      planned_start: null, planned_end: null,
                      status: 'allocated', priority: 'medium', sort_order: 0,
                      remark: null, stage_durations: order!.stage_config,
                      allocations: [], demand_allocations: [],
                      created_at: '', updated_at: '',
                    }
                    setLocalItems(prev => [...prev, newItem])
                  }}
                >+ 新增计划项</Button>
                )}
              </div>
            ) : (
              <PlanItemTable
                planOrderId={order.id}
                planOrderStatus={order.status}
                planOrderProductId={order.product_id}
                planOrderProductName={productName ?? order.items?.[0]?.product_name ?? order.title}
                planOrderRouteId={order.route_id}
                planOrderStageConfig={order.stage_config}
                items={order.items}
                isLoading={isLoading}
                onRefresh={refetch}
                onOpenStageConfig={handleOpenStageConfig}
              />
            )}

            <div style={sectionDivider} />

            {/* Section: 关联需求 — collapsible, default closed */}
            <SectionHead label="关联需求" count={order.demand_allocations?.length ?? 0} accentColor={accentColor} collapsed={!showDemands} onToggle={() => setShowDemands(v => !v)} />
            {showDemands && <DemandSection allocations={order.demand_allocations} />}

            {!changeMode && order.change_logs && order.change_logs.length > 0 && (
              <>
                <div style={sectionDivider} />
                <SectionHead label="变更历史" count={order.change_logs.length} accentColor={accentColor} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {order.change_logs.map(log => (
                    <div key={log.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '6px 10px', background: 'var(--color-surface-soft)', borderRadius: 6,
                      fontSize: 12,
                    }}>
                      <Tag style={{ flexShrink: 0, fontSize: 10, lineHeight: '16px' }}>v{log.plan_version}</Tag>
                      <span style={{ flex: 1, color: 'var(--color-charcoal)' }}>{log.change_reason}</span>
                      <span style={{ color: 'var(--color-stone)', fontSize: 11, whiteSpace: 'nowrap' }}>
                        {new Date(log.created_at).toLocaleDateString('zh-CN')}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <ReleaseConfirmModal
            orderId={order.id}
            open={releaseModalOpen}
            items={order.items}
            onClose={() => setReleaseModalOpen(false)}
            onRefresh={refetch}
          />

          {/* 工段配置 Modal */}
          <Modal
            title="工段配置"
            open={stageEditOpen}
            onOk={async () => {
              const r = await updatePlanOrder(order.id, { stage_config: stageEditForm })
              if (r.success) {
                message.success('工段配置已更新')
                setStageEditOpen(false)
                refetch()
              } else {
                message.error(r.error)
              }
            }}
            onCancel={() => setStageEditOpen(false)}
            width={560}
            destroyOnHidden
          >
            {availableStages.length === 0 && (
              <Empty description="该计划单未关联工艺路线，无法配置工段" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginBottom: 16 }} />
            )}
            {stageEditForm.map((sc, idx) => {
              // 当前行可选工段：availableStages 中排除已被其他行选中的
              const taken = stageEditForm.filter((_, i) => i !== idx).map((s) => s.stage_name)
              const selectable = availableStages.filter((n) => n === sc.stage_name || !taken.includes(n))
              return (
                <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                  <Select
                    size="small"
                    placeholder="选择工段"
                    value={sc.stage_name || undefined}
                    onChange={(v) => {
                      const next = [...stageEditForm]
                      next[idx] = { ...next[idx], stage_name: v }
                      setStageEditForm(next)
                    }}
                    options={selectable.map((n) => ({ value: n, label: n }))}
                    style={{ width: 120 }}
                  />
                  <Space.Compact>
                    <InputNumber
                      size="small" min={0.5} step={0.5}
                      value={sc.duration_hours}
                      onChange={(v) => {
                        const next = [...stageEditForm]
                        next[idx] = { ...next[idx], duration_hours: v ?? 24 }
                        setStageEditForm(next)
                      }}
                      style={{ width: 90 }}
                    />
                    <Button size="small" disabled style={{ padding: '0 6px', fontSize: 12 }}>h</Button>
                  </Space.Compact>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {STAGE_PRESET_COLORS.map((c) => (
                      <div
                        key={c}
                        onClick={() => {
                          const next = [...stageEditForm]
                          next[idx] = { ...next[idx], color: c }
                          setStageEditForm(next)
                        }}
                        style={{
                          width: 22, height: 22, borderRadius: 4,
                          backgroundColor: c,
                          border: sc.color === c ? '3px solid #1677ff' : '2px solid transparent',
                          cursor: 'pointer', transition: 'border 0.15s',
                        }}
                      />
                    ))}
                  </div>
                  <Button
                    type="text" size="small" danger
                    onClick={() => setStageEditForm((prev) => prev.filter((_, i) => i !== idx))}
                  >删除</Button>
                </div>
              )
            })}
            {(() => {
              const unused = availableStages.filter((n) => !stageEditForm.some((s) => s.stage_name === n))
              return unused.length > 0 ? (
                <Button
                  type="dashed"
                  size="small"
                  block
                  style={{ marginTop: stageEditForm.length > 0 ? 8 : 0 }}
                  onClick={() => setStageEditForm((prev) => [...prev, { stage_name: unused[0], duration_hours: 24, color: STAGE_PRESET_COLORS[prev.length % STAGE_PRESET_COLORS.length] }])}
                >
                  + 添加工段
                </Button>
              ) : null
            })()}
          </Modal>
        </>
      )}
    </Drawer>
  )
}
