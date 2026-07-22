'use client'

import { App, Button, Form, Input, InputNumber, Modal, Select, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { deriveBatches } from '@/actions/production'
import {
  fetchBatchDetailClient,
  fetchRouteGraphClient,
} from '@/lib/api/production-client'

const DEVIATION = '__deviation__'

interface Props {
  batchId: string
  onClose: () => void
}

export function DeriveModal({ batchId, onClose }: Props) {
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

  const nodeName = (id: string) => graph?.nodes.find(n => n.id === id)?.name ?? '?'
  const boundaryEdges = graph?.edges.filter(e => e.is_batch_boundary) ?? []

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const isDeviation = values.edge_id === DEVIATION
    const result = await deriveBatches(batchId, {
      edge_id: isDeviation ? null : values.edge_id,
      deviation_reason: isDeviation ? values.deviation_reason : null,
      children: values.children,
    })
    if (result.success) {
      message.success('批次已分裂')
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      queryClient.invalidateQueries({ queryKey: ['production-trace', batchId] })
      onClose()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={`批次分裂 · ${detail?.batch_no ?? ''}`}
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={560}
    >
      <Form form={form} layout="vertical" initialValues={{ children: [{}] }}>
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
              { value: DEVIATION, label: '临时偏离（未预定义的分批）' },
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
        <Form.List name="children">
          {(fields, { add, remove }) => (
            <>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>子批次</div>
              {fields.map(field => (
                <Space key={field.key} align="baseline" style={{ display: 'flex' }}>
                  <Form.Item
                    name={[field.name, 'batch_no']}
                    rules={[{ required: true, message: '批号必填' }]}
                  >
                    <Input placeholder="子批号" style={{ width: 220 }} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'quantity']}>
                    <InputNumber placeholder="数量" min={0} style={{ width: 120 }} />
                  </Form.Item>
                  {fields.length > 1 && (
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => remove(field.name)}
                    />
                  )}
                </Space>
              ))}
              <Button size="small" icon={<PlusOutlined />} onClick={() => add({})}>
                添加子批次
              </Button>
            </>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}
