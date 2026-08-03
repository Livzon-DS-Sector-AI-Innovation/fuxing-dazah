'use client'

import { useState, useMemo } from 'react'
import { App, DatePicker, Form, Input, InputNumber, Modal, Select, Button, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { createPlanOrder } from '@/actions/production'
import { fetchProductsClient, fetchRoutesClient, fetchRouteGraphClient } from '@/lib/api/production-client'
import type { CreatePlanOrderInput, StageConfigItem } from '@/types/production'
import { STAGE_PRESET_COLORS } from './constants'
import { serializeDates } from './utils'
import { PRIORITY_CONFIG } from './constants'

const PRIORITY_OPTIONS = Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 12, fontWeight: 600, color: 'var(--color-slate)',
      textTransform: 'uppercase', letterSpacing: '0.5px',
      marginBottom: 12, paddingBottom: 6,
      borderBottom: '1px solid var(--color-hairline)',
      marginTop: 20,
    }}>
      {children}
    </div>
  )
}

function StageConfigEditor({ stageConfig, onChange }: {
  stageConfig: StageConfigItem[]
  onChange: (next: StageConfigItem[]) => void
}) {
  return (
    <div style={{
      background: 'var(--color-surface-soft)',
      borderRadius: 8,
      border: '1px solid var(--color-hairline)',
      padding: 12,
      marginBottom: 16,
    }}>
      {stageConfig.map((sc, idx) => (
        <div key={`${sc.stage_name}-${idx}`} style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '6px 0',
          borderBottom: idx < stageConfig.length - 1 ? '1px solid var(--color-hairline)' : 'none',
        }}>
          {/* 工段名 */}
          <span style={{ width: 64, fontSize: 13, color: 'var(--color-charcoal)', fontWeight: 500 }}>
            {sc.stage_name}
          </span>
          {/* 时长输入 */}
          <Space.Compact>
            <InputNumber
              size="small" min={0.5} step={0.5}
              value={sc.duration_hours}
              onChange={(v) => {
                const next = [...stageConfig]
                next[idx] = { ...next[idx], duration_hours: v ?? 24 }
                onChange(next)
              }}
              style={{ width: 72 }}
            />
            <Button size="small" disabled style={{ padding: '0 6px', fontSize: 12 }}>h</Button>
          </Space.Compact>
          {/* 色块选择器 — 加大到 24px，选中态用 2px ring */}
          <div style={{ display: 'flex', gap: 6, marginLeft: 4 }}>
            {STAGE_PRESET_COLORS.map((c) => (
              <div
                key={c}
                onClick={() => {
                  const next = [...stageConfig]
                  next[idx] = { ...next[idx], color: c }
                  onChange(next)
                }}
                style={{
                  width: 24, height: 24, borderRadius: 6,
                  backgroundColor: c, cursor: 'pointer',
                  boxShadow: sc.color === c ? `0 0 0 2px var(--color-canvas), 0 0 0 4px ${c}` : 'none',
                  transition: 'box-shadow 0.15s ease',
                }}
              />
            ))}
          </div>
          {/* 删除 */}
          <Button type="text" size="small" danger
            onClick={() => onChange(stageConfig.filter((_, i) => i !== idx))}
            style={{ marginLeft: 'auto' }}
          >
            删除
          </Button>
        </div>
      ))}
      <Button size="small" type="dashed" block style={{ marginTop: 8 }}
        onClick={() => onChange([...stageConfig, { stage_name: '', duration_hours: 24, color: STAGE_PRESET_COLORS[0] }])}>
        + 添加工段
      </Button>
    </div>
  )
}

interface Props {
  open: boolean
  onClose: () => void
  onSuccess?: () => void
}

export function CreatePlanOrderModal({ open, onClose, onSuccess }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm<CreatePlanOrderInput>()

  const [selectedProductId, setSelectedProductId] = useState<string | undefined>()
  const [selectedRouteId, setSelectedRouteId] = useState<string | undefined>()
  // 用户编辑后的工段配置；null 表示尚未手动修改，使用默认值
  const [userStageConfig, setUserStageConfig] = useState<StageConfigItem[] | null>(null)

  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: () => fetchProductsClient(),
    staleTime: 30_000,
  })

  const { data: routes } = useQuery({
    queryKey: ['routes', selectedProductId],
    queryFn: () => fetchRoutesClient(selectedProductId!, 'published'),
    enabled: !!selectedProductId,
    staleTime: 30_000,
  })

  const { data: routeGraph } = useQuery({
    queryKey: ['routeGraph', selectedRouteId],
    queryFn: () => fetchRouteGraphClient(selectedRouteId!),
    enabled: !!selectedRouteId,
  })

  const stageNames = useMemo(() => {
    if (!routeGraph?.nodes) return []
    const names = new Set<string>()
    for (const node of routeGraph.nodes) {
      if (node.stage_name) names.add(node.stage_name)
    }
    return [...names]
  }, [routeGraph])

  // 默认工段配置：从工艺路线图的工段名派生，渲染期间直接计算，避免 effect 里同步 setState
  const defaultStageConfig = useMemo(() => {
    if (stageNames.length === 0) return []
    return stageNames.map((name, i) => ({
      stage_name: name,
      duration_hours: 24,
      color: STAGE_PRESET_COLORS[i % STAGE_PRESET_COLORS.length],
    }))
  }, [stageNames])

  const stageConfig = userStageConfig ?? defaultStageConfig

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const input = {
      ...serializeDates(values as unknown as Record<string, unknown>),
      stage_config: stageConfig.length > 0 ? stageConfig : undefined,
    }
    const r = await createPlanOrder(input as unknown as CreatePlanOrderInput)
    if (r.success) {
      message.success('计划单已创建')
      form.resetFields()
      setUserStageConfig(null)
      setSelectedProductId(undefined)
      setSelectedRouteId(undefined)
      onSuccess?.()
    } else {
      message.error(r.error)
    }
  }

  return (
    <Modal
      title="新建计划单"
      open={open}
      onOk={handleOk}
      onCancel={() => { form.resetFields(); setUserStageConfig(null); onClose() }}
      destroyOnHidden
      width={600}
    >
      <Form form={form} layout="vertical" initialValues={{ priority: 'medium' }}>
        {/* 基本信息 */}
        <SectionLabel>基本信息</SectionLabel>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input placeholder="例如：2026年Q3生产计划" />
        </Form.Item>

        {/* 产品与工艺 */}
        <SectionLabel>产品与工艺</SectionLabel>
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="product_id" label="产品" rules={[{ required: true, message: '请选择产品' }]} style={{ flex: 1 }}>
            <Select
              showSearch
              placeholder="搜索并选择产品"
              filterOption={(input, option) => (option?.label as string)?.toLowerCase().includes(input.toLowerCase())}
              onChange={(id: string) => { setSelectedProductId(id); form.setFieldValue('route_id', undefined); setSelectedRouteId(undefined); setUserStageConfig(null) }}
              options={(products ?? []).map((p) => ({ value: p.id, label: p.product_name }))}
            />
          </Form.Item>
          <Form.Item name="route_id" label="工艺路线" rules={[{ required: true, message: '请选择工艺路线' }]} style={{ flex: 1 }}>
            <Select
              placeholder="先选产品"
              disabled={!selectedProductId}
              onChange={(id: string) => { setSelectedRouteId(id); setUserStageConfig(null) }}
              options={(routes ?? []).map((r) => ({ value: r.id, label: `${r.name} v${r.version}` }))}
            />
          </Form.Item>
        </div>

        {/* 工段时长 */}
        {stageConfig.length > 0 && (
          <>
            <SectionLabel>工段时长</SectionLabel>
            <StageConfigEditor stageConfig={stageConfig} onChange={setUserStageConfig} />
          </>
        )}

        {/* 计划周期 */}
        <SectionLabel>计划周期</SectionLabel>
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="scheduled_start" label="开始日期" style={{ flex: 1 }}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="scheduled_end" label="结束日期" style={{ flex: 1 }}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </div>

        {/* 其他 */}
        <SectionLabel>其他</SectionLabel>
        <Form.Item name="priority" label="优先级">
          <Select options={PRIORITY_OPTIONS} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
