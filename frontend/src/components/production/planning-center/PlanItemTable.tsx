'use client'

import { useState, useEffect, useCallback } from 'react'
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
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { createPlanItem, updatePlanItem, deletePlanItem, schedulePlanItem } from '@/actions/production'
import type { PlanItem, StageConfigItem } from '@/types/production'
import { fetchProductsClient, fetchRoutesClient } from '@/lib/api/production-client'
import { ITEM_STATUS_CONFIG, PRIORITY_CONFIG } from './constants'
import dayjs from 'dayjs'

const { Text } = Typography

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
        <Form.Item name="priority" label="优先级" initialValue="medium" style={{ marginBottom: 0 }}>
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
}

export function PlanItemTable({ planOrderId, planOrderStatus, planOrderProductId, planOrderProductName, planOrderRouteId, planOrderStageConfig, items, isLoading = false, onRefresh }: Props) {
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

  const { data: productData } = useQuery({
    queryKey: ['products', productKeyword],
    queryFn: () => fetchProductsClient(productKeyword || undefined),
    staleTime: 30_000,
  })
  const products = productData ?? []

  const { data: routesData } = useQuery({
    queryKey: ['routes', selectedProductId],
    queryFn: () => fetchRoutesClient(selectedProductId!),
    enabled: !!selectedProductId,
    staleTime: 30_000,
  })
  const routes = routesData ?? []

  const nextBatchNo = useCallback((current: string): string => {
    const m = current.match(/^(.*?)(\d+)(.*)$/)
    if (!m) return current + '-1'
    const n = String(parseInt(m[2], 10) + 1).padStart(m[2].length, '0')
    return m[1] + n + m[3]
  }, [])

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
        batch_no: nextBatchNo(values.batch_no),
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

  useEffect(() => {
    if (addOpen && planOrderProductId) {
      addForm.setFieldsValue({
        product_id: planOrderProductId,
        product_name: planOrderProductName,
        route_id: planOrderRouteId,
        batch_no: '',
        priority: 'medium',
      })
      setSelectedProductId(planOrderProductId)
      setItemStages(planOrderStageConfig ? planOrderStageConfig.map(s => ({ ...s })) : [])
    }
  }, [addOpen, planOrderProductId, planOrderProductName, planOrderRouteId, planOrderStageConfig, addForm])

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

  useEffect(() => {
    if (editItem) {
      editForm.setFieldsValue({
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
      })
    }
  }, [editItem, editForm])

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const columns: ColumnsType<PlanItem> = [
    { title: '项号', dataIndex: 'item_no', key: 'item_no', width: 60 },
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 140 },
    {
      title: '计划数量', key: 'qty', width: 100,
      render: (_, r) => r.planned_quantity != null ? `${r.planned_quantity}${r.unit ? ` ${r.unit}` : ''}` : '—',
    },
    { title: '批次号', dataIndex: 'batch_no', key: 'batch_no', width: 100, render: v => v || '—' },
    { title: '设备', dataIndex: 'equipment_id', key: 'equipment_id', width: 100, render: v => v || '—' },
    {
      title: '计划时间', key: 'dates', width: 180,
      render: (_, r) => `${formatDate(r.planned_start)} ~ ${formatDate(r.planned_end)}`,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const c = ITEM_STATUS_CONFIG[s] ?? { label: s, color: 'default' }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 70,
      render: (p: string) => {
        const c = PRIORITY_CONFIG[p] ?? { label: p, color: 'default' }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_, r) => (
        <Space size="small">
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>计划项</Text>
        {canEdit && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            添加计划项
          </Button>
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
          scroll={{ x: 800 }}
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
        <Form form={addForm} layout="vertical">
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

      {/* 编辑 Modal */}
      <Modal
        title="编辑计划项"
        open={!!editItem}
        onOk={handleEdit}
        onCancel={() => { editForm.resetFields(); setItemStages([]); setEditItem(null) }}
        width={520}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
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
