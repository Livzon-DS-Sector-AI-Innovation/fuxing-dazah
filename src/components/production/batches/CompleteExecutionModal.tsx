'use client'

import { useState } from 'react'
import { App, Form, Input, InputNumber, Modal } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { completeExecution } from '@/actions/production'
import { fetchRouteGraphClient } from '@/lib/api/production-client'
import type { Execution } from '@/types/production'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'

interface Props {
  execution: Execution
  routeId: string
  onClose: () => void
  onSuccess?: () => void
}

export function CompleteExecutionModal({ execution, routeId, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', routeId],
    queryFn: () => fetchRouteGraphClient(routeId),
  })
  const node = graph?.nodes.find(n => n.id === execution.node_id)
  const endDefs = node?.fields.filter(f => f.phase === 'end') ?? []
  const outputIntermediates = (node?.intermediates ?? []).filter(im => im.direction === 'output')

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSubmitting(true)
    try {
    const result = await completeExecution(execution.id, {
      field_values: buildFieldValues(endDefs, values),
      remark: (values.remark as string) ?? null,
      intermediate_outputs: outputIntermediates.length > 0
        ? outputIntermediates.map(im => ({
            intermediate_type_id: im.intermediate_type_id,
            quantity: Number((values as Record<string, number>)[`output_qty_${im.intermediate_type_id}`]) || 0,
            unit: ((values as Record<string, string>)[`output_unit_${im.intermediate_type_id}`]) || undefined,
            intermediate_batch_no: ((values as Record<string, string>)[`output_batch_${im.intermediate_type_id}`]) || undefined,
            remark: ((values as Record<string, string>)[`output_remark_${im.intermediate_type_id}`]) || undefined,
          })).filter(o => o.quantity > 0)
        : [],
    })
    if (result.success) {
      message.success('工序已结束')
      queryClient.invalidateQueries({
        queryKey: ['production-batch-detail', execution.batch_id],
      })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      queryClient.invalidateQueries({ queryKey: ['production-trace'] })
      queryClient.invalidateQueries({ queryKey: ['production-available-outputs'] })
      onSuccess?.()
      onClose()
    } else {
      message.error(result.error)
    }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          结束工序 · {execution.node_name ?? ''}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
      okText="结束工序"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical">
        {/* ── 动态字段 ── */}
        <DynamicFieldFormItems defs={endDefs} />

        {/* ── 产出物料 ── */}
        {outputIntermediates.length > 0 && (
          <div style={{ marginTop: endDefs.length > 0 ? 8 : 0, marginBottom: 16 }}>
            {outputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{
                padding: '14px 16px', marginBottom: 10,
                borderRadius: 10, background: '#ffffff',
                border: '1px solid #ede9e4',
              }}>
                {/* 物料名称 — 突出显示 */}
                <div style={{
                  fontSize: 15, fontWeight: 600, color: '#1a1a1a',
                  marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required && (
                    <span style={{ fontSize: 11, color: '#e03131', fontWeight: 400 }}>必填</span>
                  )}
                </div>

                {/* 产出详情 */}
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 10,
                  padding: '12px 14px', borderRadius: 8,
                  background: '#fafaf8',
                }}>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <Form.Item
                      name={`output_batch_${im.intermediate_type_id}`}
                      label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>中间体批号</span>}
                      style={{ margin: 0, flex: 1 }}
                    >
                      <Input placeholder="默认使用批次号" style={{ borderRadius: 6 }} />
                    </Form.Item>

                    <Form.Item
                      name={`output_unit_${im.intermediate_type_id}`}
                      label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>单位</span>}
                      style={{ margin: 0, width: 120 }}
                    >
                      <Input placeholder={im.unit_override ?? '默认单位'} style={{ borderRadius: 6 }} />
                    </Form.Item>
                  </div>

                  <Form.Item
                    name={`output_qty_${im.intermediate_type_id}`}
                    label={<span style={{ fontSize: 12, fontWeight: 500, color: '#787671' }}>数量</span>}
                    rules={im.required ? [{ required: true, message: '请输入数量' }] : undefined}
                    style={{ margin: 0 }}
                  >
                    <InputNumber min={1} placeholder="数量" style={{ width: '100%' }} />
                  </Form.Item>
                </div>

                {/* 备注 */}
                <Form.Item
                  name={`output_remark_${im.intermediate_type_id}`}
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
