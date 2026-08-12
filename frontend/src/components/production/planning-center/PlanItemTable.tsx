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
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { usePermission } from '@/hooks/usePermission'
import { createPlanItem, updatePlanItem, deletePlanItem, schedulePlanItem } from '@/actions/production'
import type { PlanItem, StageConfigItem, PlanItemBatchProgress } from '@/types/production'
import { fetchProductsClient, fetchRoutesClient } from '@/lib/api/production-client'
import { ITEM_STATUS_CONFIG, PRIORITY_CONFIG } from './constants'
import { batchGenDayOffset, batchRhythmWarning } from './utils'
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

// 工段配置是否与计划单一致（一致时不固化快照，保持继承）
function isSameStages(
  a: StageConfigItem[] | null | undefined,
  b: StageConfigItem[] | null | undefined,
): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

// ── Stage Progress Bar ──

export function StageProgressBar({
  stageDurations,
  batchProgress,
}: {
  stageDurations?: StageConfigItem[] | null
  batchProgress?: PlanItemBatchProgress | null
}) {
  // 工序模式：段=已配置工段内的路线工序（超出配置工段的后续工序不展示），高亮按工序名匹配；无 route_nodes 时回退工段模式（旧数据）
  const stageColorMap = new Map((stageDurations ?? []).map((s) => [s.stage_name, s.color]))
  const nodes = batchProgress?.route_nodes?.length
    ? batchProgress.route_nodes.filter((n) => !!n.stage_name && stageColorMap.has(n.stage_name))
    : null
  const segments = nodes?.length
    ? nodes.map((n) => ({
        key: n.name,
        label: n.name,
        // 工序颜色跟随其所属工段的配置色（filter 已保证 stage_name 命中配置）
        color: stageColorMap.get(n.stage_name!)!,
        tip: `${n.stage_name} · ${n.name}`,
      }))
    : stageDurations?.length
      ? stageDurations.map((s) => ({
          key: s.stage_name,
          label: s.stage_name,
          color: s.color,
          tip: `${s.stage_name} · ${s.duration_hours}h`,
        }))
      : null

  if (!segments?.length) {
    return <span style={{ fontSize: 12, color: 'var(--color-stone)' }}>—</span>
  }

  const rawIdx = batchProgress?.latest_stage
    ? segments.findIndex((s) => s.key === batchProgress.latest_stage)
    : -1
  // 工序模式：最远执行工序已超出配置工段（route 在配置工段后继续）时视为配置段内全部完成
  const currentIdx = nodes?.length && rawIdx === -1 && batchProgress?.latest_stage
    ? segments.length
    : rawIdx

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 160 }}>
      {/* Segments bar */}
      <div style={{ display: 'flex', gap: 3, alignItems: 'center', height: 8 }}>
        {segments.map((s, i) => {
          const isCompleted = currentIdx >= 0 && i < currentIdx
          const isCurrent = currentIdx >= 0 && i === currentIdx
          const hasProgress = currentIdx >= 0

          return (
            <Tooltip key={i} title={s.tip}>
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
        {segments.map((s, i) => {
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
              {s.label}
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
  routes: { id: string; route_name: string }[]
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
          options={routes.map((r) => ({ value: r.id, label: `${r.route_name}` }))}
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
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:planning:submit')
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
  const [batchIntervalDays, setBatchIntervalDays] = useState(1) // m：每隔 m 天
  const [batchGroupSize, setBatchGroupSize] = useState(1) // n：生成 n 批
  const [batchGapDays, setBatchGapDays] = useState(1) // k：每批间隔 k 天
  const [batchGenLoading, setBatchGenLoading] = useState(false)
  const [batchIncludeFirst, setBatchIncludeFirst] = useState(true) // 前一项参与生成：参考项占序列第 1 位，新批次从其后续位置继续

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
        // 与计划单配置一致时不固化快照，保持继承（改计划单配置自动生效）
        stage_durations:
          itemStages.length > 0 && !isSameStages(itemStages, planOrderStageConfig)
            ? itemStages
            : undefined,
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
    // 仅当生成批次足以跨组时组间才可能重叠（不足一组时全部落在同一组内、逐批间隔互不重叠）；
    // 开启"前项参与"时参考项占组内第 1 位，新批次从第 2 位起，故跨组所需批次少一批
    if (batchCount >= batchGroupSize + (batchIncludeFirst ? 0 : 1)) {
      const warn = batchRhythmWarning(batchGroupSize, batchIntervalDays, batchGapDays)
      if (warn) { message.warning(warn); return }
    }
    const lastItem = items[items.length - 1]
    const lastStart = lastItem.planned_start ? new Date(lastItem.planned_start) : new Date()
    const lastEnd = lastItem.planned_end ? new Date(lastItem.planned_end) : new Date()

    setBatchGenLoading(true)
    let currentNo = batchStartNo
    let created = 0
    const startBase = lastStart.getTime()
    const endBase = lastEnd.getTime()
    try {
      for (let i = 1; i <= batchCount; i++) {
        // 第 i 批：参考项作序列第 0 个（或开启"前一项参与生成"时作第 1 个，新批次从第 2 位继续），
        // 第 i//n 组的起点偏移 i//n*m 天，组内第 i%n 批再间隔 (i%n)*k 天
        const seqIdx = batchIncludeFirst ? i + 1 : i
        const dayOffset = batchGenDayOffset(seqIdx, batchGroupSize, batchIntervalDays, batchGapDays)
        const msOffset = dayOffset * 86400000

        const r = await createPlanItem(planOrderId, {
          product_id: planOrderProductId,
          product_name: planOrderProductName ?? '',
          route_id: planOrderRouteId ?? undefined,
          batch_no: currentNo,
          priority: 'medium',
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
    setBatchGapDays(1)
    setBatchIncludeFirst(true)
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
      // 与计划单配置一致时不固化快照，保持继承（改计划单配置自动生效）
      stage_durations:
        itemStages.length > 0 && !isSameStages(itemStages, planOrderStageConfig)
          ? itemStages
          : undefined,
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
      width: 120,
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
      width: 100,
      render: (_, r: PlanItem) => (
        <span style={{ fontSize: 13, color: 'var(--color-charcoal)', whiteSpace: 'nowrap' }}>
          {formatDate(r.planned_start)} ~ {formatDate(r.planned_end)}
        </span>
      ),
    },
    {
      title: '数量',
      key: 'qty',
      width: 60,
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
          stageDurations={r.stage_durations ?? planOrderStageConfig}
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
          {canEdit && canSubmit && (
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
        {canEdit && canSubmit && onOpenStageConfig && (
          <Button size="small" onClick={onOpenStageConfig}>工段配置</Button>
        )}
        {canEdit && canSubmit && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={handleOpenAddModal}>
            添加计划项
          </Button>
        )}
        {canEdit && canSubmit && (
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
        <Form layout="vertical" style={{ marginTop: 4 }}>
          <Form.Item label="起始批号" style={{ marginBottom: 12 }}>
            <Input
              placeholder="如 A1"
              value={batchStartNo}
              onChange={e => setBatchStartNo(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="生成批次" style={{ marginBottom: 12 }}>
            <InputNumber
              min={1}
              value={batchCount}
              onChange={v => setBatchCount(v ?? 1)}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item
            label="前一项参与生成"
            extra="开启后，最后一项计入序列，新批次从其后一位继续；关闭则新批次与最后一项同日排入"
            style={{ marginBottom: 0 }}
          >
            <Switch checked={batchIncludeFirst} onChange={setBatchIncludeFirst} />
          </Form.Item>

          <div style={formDivider} />

          {/* 节奏规则 — 三个数字即一组序列公式，不做成"造句" */}
          <div style={sectionLabel}>节奏规则</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-steel)', marginBottom: 6 }}>每周期天数</div>
              <InputNumber
                min={1}
                value={batchIntervalDays}
                onChange={v => setBatchIntervalDays(v ?? 1)}
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-steel)', marginBottom: 6 }}>每周期批次</div>
              <InputNumber
                min={1}
                value={batchGroupSize}
                onChange={v => setBatchGroupSize(v ?? 1)}
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-steel)', marginBottom: 6 }}>批内间隔(天)</div>
              <InputNumber
                min={0}
                value={batchGapDays}
                onChange={v => setBatchGapDays(v ?? 0)}
                style={{ width: '100%' }}
              />
            </div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-slate)', marginTop: 8 }}>
            第 1 批紧接最后一项开始，之后每 {batchIntervalDays} 天重复 {batchGroupSize} 批，批内逐批间隔 {batchGapDays} 天
          </div>
        </Form>
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
