'use client'

import { useMemo, useState } from 'react'
import { App, Empty, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { startBatch } from '@/actions/production'
import { fetchRouteGraphClient } from '@/lib/api/production-client'
import type { CreatableRouteInfo } from '@/types/production'

interface Props {
  stage: string
  creatableRoutes: CreatableRouteInfo[]
  onClose: () => void
  /** 创建成功后回调：batchId/batchNo + 唯一起点工序（用于链式打开开始工序弹窗） */
  onCreated: (batchId: string, batchNo: string, startNodeId?: string) => void
}

export function StartBatchModal({ stage, creatableRoutes, onClose, onCreated }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  // 该工段作为第一工段的候选路线（父组件每次打开重新挂载，无重复渲染重置问题）
  const candidates = useMemo(
    () => creatableRoutes.filter(r => r.first_stage_name === stage),
    [creatableRoutes, stage],
  )
  const single = candidates.length === 1 ? candidates[0] : null

  const productOptions = useMemo(() => {
    const seen = new Map<string, string>()
    for (const r of candidates) {
      if (!seen.has(r.product_id)) seen.set(r.product_id, r.product_name ?? '未知产品')
    }
    return [...seen.entries()].map(([value, label]) => ({ value, label }))
  }, [candidates])

  const productId: string | undefined = Form.useWatch('product_id', form)
  const routeId: string | undefined = Form.useWatch('route_id', form)

  const routeOptions = useMemo(
    () => candidates
      .filter(r => !productId || r.product_id === productId)
      .map(r => ({ value: r.route_id, label: r.route_name })),
    [candidates, productId],
  )

  // 预取路线图：唯一起点工序作为默认首工序（key 与 StartExecutionModal 相同，共享缓存）
  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId!),
    enabled: !!routeId,
  })

  const startNodeId = useMemo(() => {
    if (!graph) return undefined
    const hasIncoming = new Set(
      graph.edges.filter(e => e.edge_type === 'normal').map(e => e.to_node_id),
    )
    const startNodes = graph.nodes.filter(n => !hasIncoming.has(n.id))
    return startNodes.length === 1 ? startNodes[0].id : undefined
  }, [graph])

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
      const result = await startBatch({
        batch_no: values.batch_no,
        product_id: values.product_id,
        route_id: values.route_id,
        quantity: values.quantity ?? null,
        unit: values.unit ?? null,
        remark: values.remark ?? null,
      })
      if (result.success) {
        const created = result.data!
        message.success(`批次 ${created.batch_no} 已创建`)
        queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
        queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        onCreated(created.id, created.batch_no, startNodeId)
      } else {
        message.error(result.error)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`新建批次 · ${stage}`}
      open
      onOk={handleOk}
      onCancel={onClose}
      okText="创建并开始工序"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
      width={480}
    >
      {candidates.length === 0 ? (
        <Empty description={`未找到以「${stage}」为第一工段的已发布路线`} />
      ) : (
        <Form
          form={form}
          layout="vertical"
          initialValues={single
            ? { product_id: single.product_id, route_id: single.route_id }
            : undefined}
        >
          <div style={{ marginBottom: 16, fontSize: 13, color: '#787671' }}>
            将创建以「{stage}」为第一工段的新批次；创建后可直接开始第一道工序。
          </div>
          <Form.Item
            name="product_id"
            label="产品"
            rules={[{ required: true, message: '请选择产品' }]}
          >
            <Select
              options={productOptions}
              onChange={() => form.setFieldValue('route_id', undefined)}
            />
          </Form.Item>
          <Form.Item
            name="route_id"
            label="工艺路线版本"
            rules={[{ required: true, message: '请选择工艺路线' }]}
          >
            <Select
              options={routeOptions}
              notFoundContent={productId ? '该产品下没有可选路线' : '请先选择产品'}
            />
          </Form.Item>
          <Form.Item
            name="batch_no"
            label="批号"
            rules={[{ required: true, message: '请输入批号' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="quantity" label="数量">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="unit" label="单位">
            <Input maxLength={20} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}
