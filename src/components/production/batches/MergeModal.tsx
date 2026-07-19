'use client'

import { App, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { mergeBatches } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchBatchesClient,
  fetchRouteGraphClient,
} from '@/lib/api/production-client'

const DEVIATION = '__deviation__'

interface Props {
  batchId: string // 默认作为第一个父批次
  productId: string
  onClose: () => void
}

export function MergeModal({ batchId, productId, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const edgeChoice = Form.useWatch('edge_id', form)

  const { data: detail } = useQuery({
    queryKey: ['production-batch-detail', batchId],
    queryFn: () => fetchBatchDetailClient(batchId),
  })
  const { data: graph } = useQuery({
    queryKey: ['production-route-graph', detail?.route_id],
    queryFn: () => fetchRouteGraphClient(detail!.route_id),
    enabled: !!detail?.route_id,
  })
  // 可选父批次：同产品下 in_progress/completed 的批次
  const { data: candidates } = useQuery({
    queryKey: ['production-batches', productId, { forMerge: true }],
    queryFn: () => fetchBatchesClient({ product_id: productId, page: 1, page_size: 100 }),
  })
  const mergeable =
    candidates?.items.filter(
      b => b.status === 'in_progress' || b.status === 'completed',
    ) ?? []

  const nodeName = (id: string) => graph?.nodes.find(n => n.id === id)?.name ?? '?'
  const boundaryEdges = graph?.edges.filter(e => e.is_batch_boundary) ?? []

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const isDeviation = values.edge_id === DEVIATION
    const result = await mergeBatches({
      parents: (values.parent_ids as string[]).map(id => ({ batch_id: id })),
      edge_id: isDeviation ? null : values.edge_id,
      deviation_reason: isDeviation ? values.deviation_reason : null,
      batch_no: values.batch_no,
      quantity: values.quantity ?? null,
    })
    if (result.success) {
      message.success('批次已合并')
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
      title="批次合并"
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
    >
      <Form form={form} layout="vertical" initialValues={{ parent_ids: [batchId] }}>
        <Form.Item
          name="parent_ids"
          label="父批次（至少 2 个）"
          rules={[
            { required: true, message: '请选择父批次' },
            {
              validator: (_, v: string[]) =>
                v && v.length >= 2
                  ? Promise.resolve()
                  : Promise.reject(new Error('合并至少需要 2 个父批次')),
            },
          ]}
        >
          <Select
            mode="multiple"
            options={mergeable.map(b => ({ value: b.id, label: b.batch_no }))}
          />
        </Form.Item>
        <Form.Item
          name="edge_id"
          label="批次边界"
          rules={[{ required: true, message: '请选择批次边界或临时偏离' }]}
        >
          <Select
            options={[
              ...boundaryEdges.map(e => ({
                value: e.id,
                label: `${nodeName(e.from_node_id)} → ${nodeName(e.to_node_id)}`,
              })),
              { value: DEVIATION, label: '临时偏离（未预定义的合并）' },
            ]}
          />
        </Form.Item>
        {edgeChoice === DEVIATION && (
          <Form.Item
            name="deviation_reason"
            label="偏离原因"
            rules={[{ required: true, message: '请说明偏离原因' }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
        )}
        <Form.Item
          name="batch_no"
          label="新批号"
          rules={[{ required: true, message: '请输入合并后的新批号' }]}
        >
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item name="quantity" label="数量">
          <InputNumber style={{ width: '100%' }} min={0} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
