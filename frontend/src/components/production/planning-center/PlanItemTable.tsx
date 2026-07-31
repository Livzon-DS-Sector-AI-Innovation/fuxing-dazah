'use client'

import { useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { createPlanItem, updatePlanItem, deletePlanItem, schedulePlanItem } from '@/actions/production'
import type { PlanItem, StageConfigItem, PlanItemBatchProgress } from '@/types/production'
import { fetchProductsClient, fetchRoutesClient } from '@/lib/api/production-client'
import { ITEM_STATUS_CONFIG, PRIORITY_CONFIG } from './constants'
import { incrementBatchNo } from '@/lib/utils'
import dayjs from 'dayjs'

// ── Form divider ──

const formDivider: React.CSSProperties = {
  height: 1,
  background: 'var(--color-hairline-soft)',
  margin: '14px 0',
}

// ── Section label ──

const sectionLabel: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--color-steel)',
  marginBottom: 8,
}

// ── Status accent strip colors ──

const ITEM_ACCENT: Record<string, string> = {
  draft: 'var(--color-stone)',
  scheduled: '#0075de',
  allocated: '#5645d4',
  in_progress: '#dd5b00',
  completed: '#1aae39',
  cancelled: '#e03131',
}

// ── Stage Progress Bar ──

export function StageProgressBar({
  stageDurations,
  batchProgress,
}: {
  stageDurations?: StageConfigItem[] | null
  batchProgress?: PlanItemBatchProgress | null
}) {
  if (!stageDurations?.length) {
    return <span style={{ fontSize: 12, color: 'var(--color-stone)' }}>—</span>
  }

  const currentIdx = batchProgress?.latest_stage
    ? stageDurations.findIndex((s) => s.stage_name === batchProgress.latest_stage)
    : -1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 160 }}>
      {/* Segments bar */}
      <div style={{ display: 'flex', gap: 3, alignItems: 'center', height: 8 }}>
        {stageDurations.map((s, i) => {
          const isCompleted = currentIdx >= 0 && i < currentIdx
          const isCurrent = currentIdx >= 0 && i === currentIdx
          const hasProgress = currentIdx >= 0

          return (
            <Tooltip key={i} title={`${s.stage_name} · ${s.duration_hours}h`}>
              <div
                style={{
                  flex: 1,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: hasProgress
                    ? isCompleted || isCurrent
                      ? s.color
                      : 'var(--color-hairline)'
                    : 'var(--color-hairline)',
                  opacity: hasProgress && !isCompleted && !isCurrent ? 0.5 : 1,
                  transition: 'background-color 0.3s ease',
                  boxShadow: isCurrent
                    ? `0 0 0 2px var(--color-canvas), 0 0 0 4px ${s.color}40`
                    : undefined,
                  position: 'relative',
                }}
              >
                {isCurrent && (
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      borderRadius: 4,
                      background: s.color,
                      animation: 'stagePulse 1.8s ease-in-out infinite',
                    }}
                  />
                )}
              </div>
            </Tooltip>
          )
        })}
      </div>
      {/* Stage labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        {stageDurations.map((s, i) => {
          const isCurrent = currentIdx >= 0 && i === currentIdx
          return (
            <span
              key={i}
              style={{
                fontSize: 10,
                lineHeight: 1.3,
                color: isCurrent ? 'var(--color-charcoal)' : 'var(--color-steel)',
                fontWeight: isCurrent ? 600 : 400,
                textAlign: 'center',
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {s.stage_name}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage Duration Editor ──

function StageDurationEditor({ stages, setStages }: {
  stages: StageConfigItem[]
  setStages: React.Dispatch<React.SetStateAction<StageConfigItem[]>>
}) {
  if (stages.length === 0) return null
  return (
    <>
      <div style={formDivider} />
      <div style={sectionLabel}>工段时长</div>
      {stages.map((s, idx) => (
        <div key={`${s.stage_name}-${idx}`} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: idx < stages.length - 1 ? 8 : 0 }}>
          <span style={{ width: 80, fontSize: 13, color: 'var(--color-charcoal)' }}>{s.stage_name}</span>
          <Space.Compact>
            <InputNumber
              size="small" min={0.5} step={0.5}
              value={s.duration_hours}
              onChange={(v) => {
                const next = [...stages]
                next[idx] = { ...next[idx], duration_hours: v ?? 24 }
                setStages(next)
              }}
              style={{ width: 80 }}
            />
            <Button size="small" disabled style={{ padding: '0 6px', fontSize: 12 }}>h</Button>
          </Space.Compact>
          <span style={{ fontSize: 12, color: 'var(--color-stone)' }}>
            {s.duration_hours}h
          </span>
        </div>
      ))}
    </>
  )
}

// ── Shared Form Fields ──

function PlanItemFormFields({
  products,
  routes,
  selectedProductId,
  onProductSelect,
  onProductSearch,
  itemStages,
  setItemStages,
}: {
  products: { id: string; product_name: string; unit: string | null }[]
  routes: { id: string; name: string; version: number }[]
  selectedProductId: string | undefined
  onProductSelect: (id: string) => void
  onProductSearch: (kw: string) => void
  itemStages: StageConfigItem[]
  setItemStages: React.Dispatch<React.SetStateAction<StageConfigItem[]>>
}) {
  return (
    <>
      {/* 产品 & 路线 */}
      <Form.Item name="product_id" label="产品" rules={[{ required: true, message: '请选择产品' }]} style={{ marginBottom: 12 }}>
        <Select
          showSearch={{ onSearch: onProductSearch, filterOption: false }}
          placeholder="搜索并选择产品"
          onChange={onProductSelect}
          options={products.map((p) => ({ value: p.id, label: p.product_name }))}
        />
      </Form.Item>
      <Form.Item name="product_name" hidden><Input /></Form.Item>
      <Form.Item name="route_id" label="工艺路线" style={{ marginBottom: 0 }}>
        <Select
          allowClear
          placeholder="先选产品"
          disabled={!selectedProductId}
          options={routes.map((r) => ({ value: r.id, label: `${r.name} v${r.version}` }))}
        />
      </Form.Item>

      <div style={formDivider} />

      {/* 批次号 + 数量 + 单位 — two-column */}
      <div style={sectionLabel}>批次信息</div>
      <Form.Item name="batch_no" label="批次号" rules={[{ required: true, message: '请输入批次号' }]} style={{ marginBottom: 12 }}>
        <Input placeholder="批次号" />
      </Form.Item>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 12px' }}>
        <Form.Item name="planned_quantity" label="计划数量" style={{ marginBottom: 0 }}>
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="unit" label="单位" style={{ marginBottom: 0 }}>
          <Input placeholder="自动填入" />
        </Form.Item>
      </div>

      <div style={formDivider} />

      {/* 排程信息 — two-column grid */}
      <div style={sectionLabel}>排程信息</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 12px' }}>
        <Form.Item name="planned_start" label="计划开始" style={{ marginBottom: 12 }}>
          <DatePicker showTime format="YYYY-MM-DD HH:mm" defaultPickerValue={dayjs().add(1, 'month')} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="planned_end" label="计划结束" style={{ marginBottom: 12 }}>
          <DatePicker showTime format="YYYY-MM-DD HH:mm" defaultPickerValue={dayjs().add(1, 'month')} style={{ width: '100%' }} />
        </Form.Item>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 12px' }}>
        <Form.Item name="equipment_id" label="设备ID" style={{ marginBottom: 12 }}>
          <Input />
        </Form.Item>
        <Form.Item name="priority" label="优先级" style={{ marginBottom: 0 }}>
          <Select
            options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
          />
        </Form.Item>
      </div>

      {/* 工段时长 — conditional */}
      <StageDurationEditor stages={itemStages} setStages={setItemStages} />

      <div style={formDivider} />

      {/* 备注 */}
      <Form.Item name="remark" label="备注" style={{ marginBottom: 0 }}>
        <Input.TextArea rows={2} />
      </Form.Item>
    </>
  )
}

// ── Main Component ──

interface Props {
  planOrderId: string
  planOrderStatus: string
  planOrderProductId?: string | null
  planOrderProductName?: string
  planOrderRouteId?: string | null
  planOrderStageConfig?: StageConfigItem[] | null
  items: PlanItem[]
  isLoading?: boolean
  onRefresh: () => void
  onOpenStageConfig?: () => void
}

export function PlanItemTable({ planOrderId, planOrderStatus, planOrderProductId, planOrderProductName, planOrderRouteId, planOrderStageConfig, items, isLoading = false, onRefresh, onOpenStageConfig }: Props) {
  const { message, modal } = App.useApp()
  const [addOpen, setAddOpen] = useState(false)
  const [addLoading, setAddLoading] = useState(false)
  const [editItem, setEditItem] = useState<PlanItem | null>(null)
  const [productKeyword, setProductKeyword] = useState('')
  const [selectedProductId, setSelectedProductId] = useState<string | undefined>()
  const [itemStages, setItemStages] = useState<StageConfigItem[]>([])
  const [addForm] = Form.useForm()
  const [editForm] = Form.useForm()
  const canEdit = planOrderStatus === 'draft'

  // 批量生成
  const [batchGenOpen, setBatchGenOpen] = useState(false)
  const [batchStartNo, setBatchStartNo] = useState('')
  const [batchCount, setBatchCount] = useState(1)
  const [batchIntervalDays, setBatchIntervalDays] = useState(1)
  const [batchGroupSize, setBatchGroupSize] = useState(1)
  const [batchGenLoading, setBatchGenLoading] = useState(false)

  const { data: productData } = useQuery({
    queryKey: ['products', productKeyword],
    queryFn: () => fetchProductsClient(productKeyword || undefined),
    staleTime: 30_000,
  })
  const products = productData ?? []

  const { data: routesData } = useQuery({
    queryKey: ['routes', selectedProductId],
    queryFn: () => fetchRoutesClient(selectedProductId!, 'published'),
    enabled: !!selectedProductId,
    staleTime: 30_000,
  })
  const routes = routesData ?? []

  const handleAdd = async () => {
    const values = await addForm.validateFields().catch(() => null)
    if (!values) return
    setAddLoading(true)
    try {
      const r = await createPlanItem(planOrderId, {
        product_id: values.product_id,
        product_name: values.product_name,
        route_id: values.route_id,
        equipment_id: values.equipment_id,
        planned_quantity: values.planned_quantity,
        unit: values.unit,
        batch_no: values.batch_no,
        priority: values.priority,
        remark: values.remark,
        stage_durations: itemStages.length > 0 ? itemStages : undefined,
      })
      if (!r.success) { message.error(r.error); return }
      if (values.planned_start || values.planned_end) {
        const newItemId = r.data!.id
        const sr = await schedulePlanItem(newItemId, {
          planned_start: values.planned_start?.toISOString(),
          planned_end: values.planned_end?.toISOString(),
          equipment_id: values.equipment_id,
        })
        if (!sr.success) { message.warning(`已创建但排程失败: ${sr.error}`) }
      }
      message.success('已添加计划项')
      addForm.setFieldsValue({
        product_id: values.product_id,
        product_name: values.product_name,
        route_id: values.route_id,
        batch_no: incrementBatchNo(values.batch_no),
        planned_quantity: undefined,
        unit: undefined,
        planned_start: undefined,
        planned_end: undefined,
        equipment_id: undefined,
        priority: 'medium',
        remark: undefined,
      })
      onRefresh()
    } finally {
      setAddLoading(false)
    }
  }

  const handleBatchGenerate = async () => {
    if (!batchStartNo || batchCount <= 0) return
    if (items.length === 0) { message.error('请先添加至少一个计划项'); return }
    if (!planOrderProductId) { message.error('计划单未关联产品，无法批量生成'); return }
    const lastItem = items[items.length - 1]
    const lastStart = lastItem.planned_start ? new Date(lastItem.planned_start) : new Date()
    const lastEnd = lastItem.planned_end ? new Date(lastItem.planned_end) : new Date()

    setBatchGenLoading(true)
    let currentNo = batchStartNo
    let created = 0
    const startBase = lastStart.getTime()
    const endBase = lastEnd.getTime()
    try {
      for (let i = 0; i < batchCount; i++) {
        const idx = i + 1
        const dayOffset = Math.floor(idx / batchGroupSize) * batchIntervalDays + (idx % batchGroupSize)
        const msOffset = dayOffset * 86400000

        const r = await createPlanItem(planOrderId, {
          product_id: planOrderProductId,
          product_name: planOrderProductName ?? '',
          route_id: planOrderRouteId ?? undefined,
          batch_no: currentNo,
          priority: 'medium',
          stage_durations: planOrderStageConfig?.length ? planOrderStageConfig : undefined,
        })
        if (!r.success) { message.error(`批号 ${currentNo} 创建失败: ${r.error}`); break }

        const newItemId = r.data!.id
        await schedulePlanItem(newItemId, {
          planned_start: new Date(startBase + msOffset).toISOString(),
          planned_end: new Date(endBase + msOffset).toISOString(),
        })
        created++
        currentNo = incrementBatchNo(currentNo)
      }
      if (created > 0) {
        message.success(`已生成 ${created} 个计划项`)
        setBatchGenOpen(false)
        onRefresh()
      }
    } finally {
      setBatchGenLoading(false)
    }
  }

  const handleOpenBatchGen = () => {
    const lastItem = items[items.length - 1]
    setBatchStartNo(lastItem?.batch_no ? incrementBatchNo(lastItem.batch_no) : '')
    setBatchCount(1)
    setBatchIntervalDays(1)
    setBatchGroupSize(1)
    setBatchGenOpen(true)
  }

  const handleEdit = async () => {
    const values = await editForm.validateFields().catch(() => null)
    if (!values || !editItem) return
    const r = await updatePlanItem(editItem.id, {
      product_name: values.product_name,
      route_id: values.route_id,
      equipment_id: values.equipment_id,
      planned_quantity: values.planned_quantity,
      unit: values.unit,
      batch_no: values.batch_no,
      priority: values.priority,
      remark: values.remark,
      stage_durations: itemStages.length > 0 ? itemStages : undefined,
    })
    if (!r.success) { message.error(r.error); return }
    if (values.planned_start || values.planned_end) {
      const sr = await schedulePlanItem(editItem.id, {
        planned_start: values.planned_start?.toISOString(),
        planned_end: values.planned_end?.toISOString(),
        equipment_id: values.equipment_id,
      })
      if (!sr.success) { message.warning(`已更新但排程失败: ${sr.error}`) }
    }
    message.success('已更新')
    setEditItem(null)
    setItemStages([])
    onRefresh()
  }

  const handleDelete = (item: PlanItem) => {
    modal.confirm({
      title: `删除计划项「${item.product_name}」?`,
      content: '删除后不可恢复。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const r = await deletePlanItem(item.id)
        if (r.success) { message.success('已删除'); onRefresh() }
        else { message.error(r.error) }
      },
    })
  }

  const handleOpenAddModal = () => {
    setSelectedProductId(planOrderProductId ?? undefined)
    setItemStages(planOrderStageConfig ? planOrderStageConfig.map(s => ({ ...s })) : [])
    setAddOpen(true)
  }

  const openEditModal = (item: PlanItem) => {
    setEditItem(item)
    setSelectedProductId(item.product_id)
    setItemStages(
      item.stage_durations?.length
        ? item.stage_durations.map(s => ({ ...s }))
        : planOrderStageConfig
          ? planOrderStageConfig.map(s => ({ ...s }))
          : []
    )
  }

  const formatDate = (d: string | null) => {
    if (!d) return '—'
    return dayjs(d).format('MM/DD')
  }

  const columns: ColumnsType<PlanItem> = [
    {
      title: '批次号',
      dataIndex: 'batch_no',
      key: 'batch_no',
      width: 150,
      render: (v: string, r: PlanItem) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--color-charcoal)' }}>
            {v || '—'}
          </span>
          <span style={{ fontSize: 11, color: 'var(--color-steel)' }}>
            {r.product_name || '—'}
            {r.equipment_id ? ` · ${r.equipment_id}` : ''}
          </span>
        </div>
      ),
    },
    {
      title: '计划时间',
      key: 'dates',
      width: 130,
      render: (_, r: PlanItem) => (
        <span style={{ fontSize: 13, color: 'var(--color-charcoal)', whiteSpace: 'nowrap' }}>
          {formatDate(r.planned_start)} ~ {formatDate(r.planned_end)}
        </span>
      ),
    },
    {
      title: '数量',
      key: 'qty',
      width: 90,
      render: (_, r: PlanItem) => (
        <span style={{ fontSize: 13, color: 'var(--color-charcoal)' }}>
          {r.planned_quantity != null ? `${r.planned_quantity}${r.unit ? ` ${r.unit}` : ''}` : '—'}
        </span>
      ),
    },
    {
      title: '工序进度',
      key: 'stage_progress',
      width: 200,
      render: (_, r: PlanItem) => (
        <StageProgressBar
          stageDurations={r.stage_durations}
          batchProgress={r.batch_progress}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 75,
      render: (s: string) => {
        const c = ITEM_STATUS_CONFIG[s] ?? { label: s, color: 'default' }
        return (
          <Tag
            color={c.color}
            style={{ fontSize: 11, lineHeight: '18px', margin: 0, borderRadius: 4 }}
          >
            {c.label}
          </Tag>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_, r: PlanItem) => (
        <Space size={4}>
          {canEdit && (
            <>
              <Button size="small" type="link" onClick={() => openEditModal(r)}>编辑</Button>
              <Button size="small" type="link" danger onClick={() => handleDelete(r)}>删除</Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  if (isLoading) return <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>

  const handleProductSelect = (id: string, form: typeof addForm) => {
    setSelectedProductId(id)
    const p = products.find((t) => t.id === id)
    if (p) {
      form.setFieldsValue({ product_name: p.product_name, unit: p.unit || undefined })
    }
  }

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        {canEdit && onOpenStageConfig && (
          <Button size="small" onClick={onOpenStageConfig}>工段配置</Button>
        )}
        {canEdit && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={handleOpenAddModal}>
            添加计划项
          </Button>
        )}
        {canEdit && (
          <Tooltip title={items.length === 0 ? '请先添加至少一个计划项' : undefined}>
            <span>
              <Button size="small" disabled={items.length === 0} onClick={handleOpenBatchGen}>批量生成</Button>
            </span>
          </Tooltip>
        )}
      </div>

      {items.length === 0 ? (
        <Empty description="暂无计划项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table<PlanItem>
          dataSource={items}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 780 }}
          onRow={(record) => ({
            style: {
              borderLeft: `3px solid ${ITEM_ACCENT[record.status] ?? ITEM_ACCENT.draft}`,
            },
          })}
        />
      )}

      {/* 添加 Modal */}
      <Modal
        title="添加计划项"
        open={addOpen}
        onOk={handleAdd}
        confirmLoading={addLoading}
        mask={{ closable: false }}
        onCancel={() => { addForm.resetFields(); setItemStages([]); setAddOpen(false) }}
        width={520}
        destroyOnHidden
      >
        <Form form={addForm} layout="vertical" initialValues={{
            product_id: planOrderProductId ?? undefined,
            product_name: planOrderProductName ?? undefined,
            route_id: planOrderRouteId ?? undefined,
            batch_no: '',
            priority: 'medium',
          }}>
          <PlanItemFormFields
            products={products}
            routes={routes}
            selectedProductId={selectedProductId}
            onProductSelect={(id) => handleProductSelect(id, addForm)}
            onProductSearch={setProductKeyword}
            itemStages={itemStages}
            setItemStages={setItemStages}
          />
        </Form>
      </Modal>

      {/* 批量生成 Modal */}
      <Modal
        title="批量生成计划项"
        open={batchGenOpen}
        onOk={handleBatchGenerate}
        confirmLoading={batchGenLoading}
        onCancel={() => setBatchGenOpen(false)}
        width={520}
        destroyOnHidden
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span style={{ fontSize: 13, width: 70, flexShrink: 0 }}>起始批号</span>
            <Input placeholder="如 A1" value={batchStartNo} onChange={e => setBatchStartNo(e.target.value)} style={{ flex: 1 }} />
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span style={{ fontSize: 13, width: 70, flexShrink: 0 }}>数量</span>
            <InputNumber min={1} value={batchCount} onChange={v => setBatchCount(v ?? 1)} style={{ flex: 1 }} />
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span style={{ fontSize: 13, width: 70, flexShrink: 0 }}>间隔规则</span>
            <span style={{ fontSize: 13 }}>每</span>
            <InputNumber min={1} value={batchIntervalDays} onChange={v => setBatchIntervalDays(v ?? 1)} style={{ width: 60 }} />
            <span style={{ fontSize: 13 }}>天生成</span>
            <InputNumber min={1} value={batchGroupSize} onChange={v => setBatchGroupSize(v ?? 1)} style={{ width: 60 }} />
            <span style={{ fontSize: 13 }}>批</span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-slate)', marginTop: 4 }}>
            批号自动取最后一项递增；日期基于最后一项的时间按规则偏移，保持相同持续时长
          </div>
        </div>
      </Modal>

      {/* 编辑 Modal */}
      <Modal
        title="编辑计划项"
        open={!!editItem}
        onOk={handleEdit}
        onCancel={() => { editForm.resetFields(); setItemStages([]); setEditItem(null) }}
        width={520}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" key={editItem?.id} initialValues={editItem ? {
            product_id: editItem.product_id,
            product_name: editItem.product_name,
            route_id: editItem.route_id,
            equipment_id: editItem.equipment_id,
            planned_quantity: editItem.planned_quantity,
            unit: editItem.unit,
            batch_no: editItem.batch_no,
            planned_start: editItem.planned_start ? dayjs(editItem.planned_start) : undefined,
            planned_end: editItem.planned_end ? dayjs(editItem.planned_end) : undefined,
            priority: editItem.priority,
            remark: editItem.remark,
          } : undefined}>
          <PlanItemFormFields
            products={products}
            routes={routes}
            selectedProductId={selectedProductId}
            onProductSelect={(id) => handleProductSelect(id, editForm)}
            onProductSearch={setProductKeyword}
            itemStages={itemStages}
            setItemStages={setItemStages}
          />
        </Form>
      </Modal>
    </div>
  )
}
