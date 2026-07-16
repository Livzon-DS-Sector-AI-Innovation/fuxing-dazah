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

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const result = await completeExecution(execution.id, {
      field_values: buildFieldValues(endDefs, values),
      remark: (values.remark as string) ?? null,
    })
    if (result.success) {
      message.success('工序已结束')
      queryClient.invalidateQueries({
        queryKey: ['production-batch-detail', execution.batch_id],
      })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
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
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
