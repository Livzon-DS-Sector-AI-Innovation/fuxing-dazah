'use client'

import { App, Form, Input, Modal } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { completeExecution } from '@/actions/production'
import { fetchRouteGraphClient } from '@/lib/api/production-client'
import type { Execution } from '@/types/production'
import { DynamicFieldFormItems, buildFieldValues } from './DynamicFieldFormItems'

interface Props {
  execution: Execution
  routeId: string
  onClose: () => void
}

export function CompleteExecutionModal({ execution, routeId, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()

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
      onClose()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={`结束工序 · ${execution.node_name ?? ''}`}
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={520}
    >
      <Form form={form} layout="vertical">
        <DynamicFieldFormItems defs={endDefs} />
        {outputIntermediates.length > 0 && (
          <>
            <div style={{ marginBottom: 8, fontWeight: 600, fontSize: 13, color: '#555' }}>
              中间体产出
            </div>
            {outputIntermediates.map(im => (
              <div key={im.intermediate_type_id} style={{ marginBottom: 8, padding: 8, background: '#fafafa', borderRadius: 6 }}>
                <span style={{ fontSize: 12, color: '#888' }}>
                  {im.intermediate_type_name ?? im.intermediate_type_id}
                  {im.required ? ' *' : ''}
                </span>
                <Form.Item
                  name={`output_batch_${im.intermediate_type_id}`}
                  label="中间体批号"
                  style={{ marginBottom: 4 }}
                >
                  <Input size="small" placeholder="默认使用批次号" />
                </Form.Item>
                <Form.Item
                  name={`output_qty_${im.intermediate_type_id}`}
                  label="数量"
                  rules={im.required ? [{ required: true, message: '请输入' }] : undefined}
                  style={{ marginBottom: 4 }}
                >
                  <Input size="small" type="number" placeholder="数量" />
                </Form.Item>
                <Form.Item name={`output_unit_${im.intermediate_type_id}`} label="单位" style={{ marginBottom: 4 }}>
                  <Input size="small" placeholder={im.unit_override ?? '默认单位'} />
                </Form.Item>
                <Form.Item name={`output_remark_${im.intermediate_type_id}`} label="备注" style={{ marginBottom: 0 }}>
                  <Input size="small" placeholder="可选" />
                </Form.Item>
              </div>
            ))}
          </>
        )}
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
