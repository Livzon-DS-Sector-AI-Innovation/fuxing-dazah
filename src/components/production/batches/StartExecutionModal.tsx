'use client'

import { useMemo, useEffect, useState } from 'react'
import { App, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { startExecution, fetchNodeAssignments } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchRouteGraphClient,
} from '@/lib/api/production-client'
import { fetchEquipmentsClient } from '@/lib/api/equipment-client'
import { UserSelect } from '@/components/shared'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'
import { fetchAvailableOutputs } from '@/actions/production'

interface Props {
  batchId: string
  onClose: () => void
  defaultNodeId?: string
}

export function StartExecutionModal({ batchId, onClose, defaultNodeId }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)
  const nodeId: string | undefined = Form.useWatch('node_id', form)
  const watchedValues: Record<string, unknown> | undefined = Form.useWatch([], form)

  const { data: detail } = useQuery({
    queryKey: ['production-batch-detail', batchId],
    queryFn: () => fetchBatchDetailClient(batchId),
  })
  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', detail?.route_id],
    queryFn: () => fetchRouteGraphClient(detail!.route_id),
    enabled: !!detail?.route_id,
  })
  const { data: equipmentData } = useQuery({
    queryKey: ['production-equipments'],
    queryFn: () => fetchEquipmentsClient({ page: 1, page_size: 100 }),
  })

  const { legalNodeIds } = useMemo(() => {
    if (!graph || !detail) return { legalNodeIds: new Set<string>() }
    const completed = new Set(
      detail.executions.filter(e => e.status === 'completed').map(e => e.node_id),
    )
    const inProgress = new Set(
      detail.executions.filter(e => e.status === 'in_progress').map(e => e.node_id),
    )
    const legal = new Set<string>()
    if (completed.size === 0 && inProgress.size === 0) {
      if (detail.entry_node_id) {
        legal.add(detail.entry_node_id)
      } else {
        const hasIncoming = new Set(
          graph.edges.filter(e => e.edge_type === 'normal').map(e => e.to_node_id),
        )
        graph.nodes.forEach(n => {
          if (!hasIncoming.has(n.id)) legal.add(n.id)
        })
      }
    } else {
      graph.edges.forEach(e => {
        if (completed.has(e.from_node_id)) legal.add(e.to_node_id)
        if (e.allow_overlap && !e.is_batch_boundary && inProgress.has(e.from_node_id)) {
          legal.add(e.to_node_id)
        }
      })
    }
    return { legalNodeIds: legal }
  }, [graph, detail])

  const nodeOptions = useMemo(() => {
    if (!graph) return []
    const legal = graph.nodes.filter(n => legalNodeIds.has(n.id))
    const others = graph.nodes.filter(n => !legalNodeIds.has(n.id))
    return [...legal, ...others].map(n => ({
      value: n.id,
      label: `${n.name}（${n.node_code}）${legalNodeIds.has(n.id) ? ' [推荐]' : ''}`,
    }))
  }, [graph, legalNodeIds])

  const { data: nodeAssignmentsData } = useQuery({
    queryKey: ['production-node-assignments', detail?.route_id, nodeId],
    queryFn: async () => {
      if (!detail?.route_id || !nodeId) return []
      const r = await fetchNodeAssignments(detail.route_id, nodeId)
      return r.success ? (r.data ?? []) : []
    },
    enabled: !!(detail?.route_id && nodeId),
    staleTime: 30_000,
  })

  useEffect(() => {
    if (defaultNodeId && graph) {
      const currentNode = form.getFieldValue('node_id')
      if (!currentNode) {
        form.setFieldsValue({ node_id: defaultNodeId })
      }
    }
  }, [defaultNodeId, graph, form])

  useEffect(() => {
    if (nodeAssignmentsData?.length) {
      // 仅在字段为空时自动填充，避免覆盖用户手动选择
      const currentOwner = form.getFieldValue('owner_id')
      if (!currentOwner) {
        form.setFieldsValue({ owner_id: nodeAssignmentsData[0].user_id })
      }
    }
  }, [nodeId, nodeAssignmentsData, form])

  const selectedNode = graph?.nodes.find(n => n.id === nodeId)
  const startDefs = selectedNode?.fields.filter(f => f.phase === 'start') ?? []
  const needsDeviation = !!nodeId && !legalNodeIds.has(nodeId)
  const inputIntermediates = (selectedNode?.intermediates ?? []).filter(im => im.direction === 'input')

  const { data: batchOutputs, isError: outputsError } = useQuery({
    queryKey: ['production-available-outputs'],
    queryFn: async () => {
      const r = await fetchAvailableOutputs()
      if (!r.success) throw new Error(r.error ?? '获取可用产出失败')
      return r.data ?? []
    },
    enabled: inputIntermediates.length > 0,
  })

  const getOutputOptions = (intermediateTypeId: string) =>
    (batchOutputs ?? [])
      .filter(o => o.intermediate_type_id === intermediateTypeId)
      .map(o => ({
        value: o.id,
        label: `${o.intermediate_type_name ?? '?'} / ${o.intermediate_batch_no ?? o.batch_no ?? '-'} / ${o.quantity}${o.unit}`,
      }))

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
    const ownerId: string | undefined = values.owner_id
    const result = await startExecution(batchId, {
      node_id: values.node_id,
      owner_id: ownerId ?? null,
      owner_name: null,
      equipment_ids: (values.equipment_ids as string[]) ?? [],
      field_values: buildFieldValues(startDefs, values),
      deviation_reason: needsDeviation ? (values.deviation_reason as string) : null,
      remark: (values.remark as string) ?? null,
      intermediate_consumptions: inputIntermediates.length > 0
        ? inputIntermediates.flatMap(im => {
            const outputIds = (values as Record<string, string[]>)[`consume_output_${im.intermediate_type_id}`] ?? []
            const remark = ((values as Record<string, string>)[`consume_remark_${im.intermediate_type_id}`]) || undefined
            return outputIds
              .map(outputId => ({
                intermediate_type_id: im.intermediate_type_id,
                output_id: outputId,
                quantity: Number((values as Record<string, number>)[`consume_qty_${im.intermediate_type_id}_${outputId}`]) || 0,
                remark,
              }))
              .filter(c => c.quantity > 0)
          })
        : [],
    })
    if (result.success) {
      message.success('工序已开始')
      queryClient.invalidateQueries({ queryKey: ['production-batch-detail', batchId] })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      queryClient.invalidateQueries({ queryKey: ['production-trace'] })
      queryClient.invalidateQueries({ queryKey: ['production-available-outputs'] })
      onClose()
    } else {
      message.error(result.error)
    }
    } finally {
      setSubmitting(false)
    }
  }

  const equipmentOptions = useMemo(() => (equipmentData?.items ?? []).map(
    (e: { id: string; name: string; equipment_no: string }) => ({
      value: e.id,
      label: `${e.name}（${e.equipment_no}）`,
    }),
  ), [equipmentData])

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          开始工序 · {detail?.batch_no ?? ''}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={600}
      okText="开始工序"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical">
        {/* ── 工序节点 ── */}
        <Form.Item
          name="node_id"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>工序节点</span>}
          rules={[{ required: true, message: '请选择工序节点' }]}
        >
          <Select options={nodeOptions} showSearch placeholder="选择要开始的工序" style={{ borderRadius: 8 }} />
        </Form.Item>

        {/* ── 偏离原因 ── */}
        {needsDeviation && (
          <Form.Item
            name="deviation_reason"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>偏离原因</span>}
            rules={[{ required: true, message: '该流转未在工艺路线中定义，必须说明偏离原因' }]}
          >
            <Input.TextArea rows={2} placeholder="该流转未在工艺路线中定义，请说明原因" style={{ borderRadius: 8 }} />
          </Form.Item>
        )}

        {/* ── 基础信息区 ── */}
        <div style={{
          padding: '16px', borderRadius: 10, marginBottom: 16,
          background: '#fafaf8', border: '1px solid #ede9e4',
        }}>
          <Form.Item
            name="owner_id"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>工序负责人</span>}
          >
            <UserSelect placeholder="选择工序负责人" style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item
            name="equipment_ids"
            label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>使用设备</span>}
            style={{ marginBottom: 0 }}
          >
            <Select
              mode="multiple"
              allowClear
              showSearch
              placeholder="选择设备"
              options={equipmentOptions}
              style={{ borderRadius: 8 }}
            />
          </Form.Item>
        </div>

        {/* ── 动态字段 ── */}
        <DynamicFieldFormItems defs={startDefs} />

        {/* ── 消耗物料 ── */}
        {inputIntermediates.length > 0 && (
          <div style={{ marginTop: 8, marginBottom: 16 }}>
            {outputsError && (
              <div style={{
                marginBottom: 10, padding: '8px 12px', borderRadius: 6,
                background: '#fff2f0', color: '#e03131', fontSize: 12,
                border: '1px solid #ffccc7',
              }}>
                可用产出加载失败，请稍后重试
              </div>
            )}

            {inputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{
                padding: '14px 16px', marginBottom: 10,
                borderRadius: 10, background: '#ffffff',
                border: '1px solid #ede9e4',
              }}>
                {/* 物料名称 — 突出显示 */}
                <div style={{
                  fontSize: 15, fontWeight: 600, color: '#1a1a1a',
                  marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required && (
                    <span style={{ fontSize: 11, color: '#e03131', fontWeight: 400 }}>必填</span>
                  )}
                </div>

                {/* 选择产出批次 */}
                <Form.Item
                  name={`consume_output_${im.intermediate_type_id}`}
                  rules={im.required ? [{ required: true, message: '请选择产出批次' }] : undefined}
                  style={{ marginBottom: 10 }}
                >
                  <Select
                    mode="multiple"
                    options={getOutputOptions(im.intermediate_type_id)}
                    placeholder="选择上游产出批次"
                    allowClear
                    showSearch
                    style={{ borderRadius: 8 }}
                  />
                </Form.Item>

                {/* 每个选中产出的消耗数量 */}
                {(() => {
                  const selectedIds = (watchedValues?.[`consume_output_${im.intermediate_type_id}`] as string[]) ?? []
                  if (!selectedIds.length) return null
                  return (
                    <div style={{
                      display: 'flex', flexDirection: 'column', gap: 8,
                      padding: '10px 12px', borderRadius: 8,
                      background: '#fafaf8',
                    }}>
                      {selectedIds.map(outputId => {
                        const output = (batchOutputs ?? []).find(o => o.id === outputId)
                        const label = output
                          ? (output.intermediate_batch_no ?? output.batch_no ?? outputId.slice(0, 8))
                          : outputId.slice(0, 8)
                        return (
                          <div key={outputId} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{
                              fontSize: 13, fontWeight: 500, color: '#37352f', flex: 1,
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}>
                              {label}
                            </span>
                            <Form.Item
                              name={`consume_qty_${im.intermediate_type_id}_${outputId}`}
                              rules={im.required ? [{ required: true, message: '请输入' }] : undefined}
                              style={{ margin: 0, width: 140 }}
                            >
                              <InputNumber
                                min={1}
                                placeholder={`消耗数量${output?.unit ? ` (${output.unit})` : ''}`}
                                style={{ width: '100%' }}
                              />
                            </Form.Item>
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}

                {/* 备注 */}
                <Form.Item
                  name={`consume_remark_${im.intermediate_type_id}`}
                  style={{ marginBottom: 0, marginTop: 10 }}
                >
                  <Input placeholder="备注（可选）" style={{ borderRadius: 6 }} />
                </Form.Item>
              </div>
            ))}
          </div>
        )}

        {/* ── 全局备注 ── */}
        <Form.Item
          name="remark"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>备注</span>}
        >
          <Input.TextArea rows={2} placeholder="备注信息（可选）" style={{ borderRadius: 8 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
