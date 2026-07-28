'use client'

import { useState, useMemo } from 'react'
import {
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPlanOrderClient } from '@/lib/api/production-client'
import {
  updatePlanOrder,
  confirmPlanOrder,
  closePlanOrder,
  deletePlanOrder,
} from '@/actions/production'
import { StageConfigItem, type PlanOrderDetail } from '@/types/production'
import { fetchProductsClient, fetchRoutesClient } from '@/lib/api/production-client'
import { PlanItemTable } from './PlanItemTable'
import { ReleaseConfirmModal } from './ReleaseConfirmModal'
import { STATUS_CONFIG, PRIORITY_CONFIG, STAGE_PRESET_COLORS } from './constants'

const { Text } = Typography

// ── Status accent color helper ──

const STATUS_ACCENT: Record<string, string> = {
  blue: 'var(--color-primary)',
  purple: 'var(--color-primary)',
  green: 'var(--color-success)',
  default: 'var(--color-stone)',
  orange: 'var(--color-warning)',
  red: 'var(--color-error)',
}

// ── Sub-components ──

function InlineEditForm({ form, onSave, onCancel }: {
  form: FormInstance
  onSave: () => Promise<void>
  onCancel: () => void
}) {
  return (
    <Form form={form} layout="vertical" style={{ animation: 'fadeIn 0.2s ease' }}>
      <Form.Item name="title" label="标题" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
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

function PlanItemSection({ order, productFilter, setProductFilter, productNames, onOpenStageConfig, onRefresh, isLoading }: {
  order: PlanOrderDetail
  productFilter: string | undefined
  setProductFilter: (v: string | undefined) => void
  productNames: string[]
  onOpenStageConfig: () => void
  onRefresh: () => void
  isLoading: boolean
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Select
          placeholder="全部分类"
          allowClear
          size="small"
          style={{ width: 180 }}
          value={productFilter}
          onChange={setProductFilter}
          options={productNames.map((n) => ({ value: n, label: n }))}
        />
        {order.status === 'draft' && (
          <Button size="small" onClick={onOpenStageConfig}>工段配置</Button>
        )}
      </div>
      <PlanItemTable
        planOrderId={order.id}
        planOrderStatus={order.status}
        planOrderProductId={order.product_id}
        planOrderProductName={order.items?.[0]?.product_name ?? order.title}
        planOrderRouteId={order.route_id}
        planOrderStageConfig={order.stage_config}
        items={productFilter ? order.items.filter((i) => i.product_name === productFilter) : order.items}
        isLoading={isLoading}
        onRefresh={onRefresh}
      />
    </div>
  )
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

function SectionHead({ label, count, accentColor }: { label: string; count?: number; accentColor: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
      <span style={{
        width: 3, height: 16, borderRadius: 2,
        backgroundColor: accentColor,
        display: 'inline-block', flexShrink: 0,
      }} />
      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-slate)' }}>
        {label}{count != null ? ` (${count})` : ''}
      </span>
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
}

export function PlanOrderDetailDrawer({ orderId, onClose }: Props) {
  const { modal, message } = App.useApp()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editForm] = Form.useForm()
  const [releaseModalOpen, setReleaseModalOpen] = useState(false)
  const [productFilter, setProductFilter] = useState<string | undefined>()
  const [stageEditOpen, setStageEditOpen] = useState(false)
  const [stageEditForm, setStageEditForm] = useState<StageConfigItem[]>([])

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

  const productName = useMemo(() => {
    if (!order?.product_id || !products) return null
    return products.find((p: any) => p.id === order.product_id)?.product_name ?? null
  }, [order?.product_id, products])

  const routeName = useMemo(() => {
    if (!order?.route_id || !routes) return null
    const r = routes.find((r: any) => r.id === order.route_id)
    return r ? `${r.name} v${r.version}` : null
  }, [order?.route_id, routes])

  const productNames = useMemo(() => {
    if (!order?.items) return []
    return [...new Set(order.items.map((i) => i.product_name))]
  }, [order])

  const status = order ? (STATUS_CONFIG[order.status] ?? { label: order.status, color: 'default' }) : null
  const accentColor = STATUS_ACCENT[status?.color ?? ''] ?? STATUS_ACCENT.default

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const handleEdit = () => {
    editForm.setFieldsValue({
      title: order?.title,
      scheduled_start: order?.scheduled_start ? order.scheduled_start.slice(0, 10) : undefined,
      scheduled_end: order?.scheduled_end ? order.scheduled_end.slice(0, 10) : undefined,
      priority: order?.priority,
      remark: order?.remark,
    })
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

  const handleConfirm = async () => {
    if (!orderId) return
    const r = await confirmPlanOrder(orderId)
    if (r.success) {
      message.success('已确认')
      refetch()
    } else {
      message.error(r.error)
    }
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
          onClose()
        } else {
          message.error(r.error)
        }
      },
    })
  }

  const handleOpenStageConfig = () => {
    if (!order) return
    setStageEditForm(order.stage_config ? order.stage_config.map((s: StageConfigItem) => ({ ...s })) : [])
    setStageEditOpen(true)
  }

  return (
    <Drawer
      title="计划单详情"
      open={!!orderId}
      onClose={onClose}
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
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              {order.status === 'draft' && (
                <>
                  <Button type="primary" size="small" onClick={handleConfirm}>确认</Button>
                  <Button size="small" onClick={handleEdit}>编辑</Button>
                  <Button size="small" danger onClick={handleDelete}>删除</Button>
                </>
              )}
              {order.status === 'confirmed' && (
                <>
                  <Button size="small" onClick={handleEdit}>编辑</Button>
                  <Button type="primary" size="small" onClick={() => setReleaseModalOpen(true)}>下达</Button>
                  <Button size="small" onClick={async () => {
                    const r = await closePlanOrder(order.id)
                    if (r.success) { message.success('已关闭'); refetch() }
                    else message.error(r.error)
                  }}>关闭</Button>
                </>
              )}
              {(order.status === 'released' || order.status === 'completed') && (
                <Button size="small" onClick={async () => {
                  const r = await closePlanOrder(order.id)
                  if (r.success) { message.success('已关闭'); refetch() }
                  else message.error(r.error)
                }}>关闭</Button>
              )}
            </div>
          </div>

          {/* Body — left accent strip + sections */}
          <div style={{ padding: '20px 24px 20px 20px' }}>
            {/* Section: 基本信息 */}
            <SectionHead label="基本信息" accentColor={accentColor} />
            {editing ? (
              <InlineEditForm form={editForm} onSave={handleSaveEdit} onCancel={() => setEditing(false)} />
            ) : (
              <DetailView order={order} productName={productName} routeName={routeName} formatDate={formatDate} />
            )}

            <div style={sectionDivider} />

            {/* Section: 计划项 */}
            <SectionHead label="计划项" count={order.items?.length ?? 0} accentColor={accentColor} />
            <PlanItemSection
              order={order}
              productFilter={productFilter}
              setProductFilter={setProductFilter}
              productNames={productNames}
              onOpenStageConfig={handleOpenStageConfig}
              onRefresh={refetch}
              isLoading={isLoading}
            />

            <div style={sectionDivider} />

            {/* Section: 关联需求 */}
            <SectionHead label="关联需求" count={order.demand_allocations?.length ?? 0} accentColor={accentColor} />
            <DemandSection allocations={order.demand_allocations} />
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
            {stageEditForm.length === 0 ? (
              <Empty description="暂无工段配置" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              stageEditForm.map((sc, idx) => (
                <div key={`${sc.stage_name}-${idx}`} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ width: 80, fontSize: 13 }}>{sc.stage_name}</span>
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
              ))
            )}
          </Modal>
        </>
      )}
    </Drawer>
  )
}
