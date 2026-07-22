'use client'

import { App, Form, Input, InputNumber, Modal, Button } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { receiveAndStart } from '@/actions/production'
import type { WorkbenchItem } from '@/types/production'

interface Props {
  item: WorkbenchItem
  onClose: () => void
}

export function ReceiveModal({ item, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  const isMerge = item.parent_batch_ids.length > 1

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return

    const children = (values.children as Array<{ batch_no: string; quantity?: number; unit?: string }> | undefined) ?? []

    const result = await receiveAndStart({
      parent_batch_ids: item.parent_batch_ids,
      edge_id: item.boundary_edge_id,
      deviation_reason: (values.deviation_reason as string) || null,
      children: children.map(c => ({
        batch_no: c.batch_no,
        ...(c.quantity != null ? { quantity: c.quantity } : {}),
        ...(c.unit ? { unit: c.unit } : {}),
      })),
      start_execution: false,
      execution: null,
    })

    if (result.success) {
      message.success('接收成功')
      queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
      queryClient.invalidateQueries({ queryKey: ['production-batches'] })
      onClose()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={`${isMerge ? '合并' : '分裂'}接收 · ${item.node_name || item.stage_name || '批次边界'}`}
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={500}
      okText="接收"
      cancelText="取消"
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ children: [{ batch_no: '', quantity: undefined, unit: undefined }] }}
      >
        {/* 父批次 */}
        <div style={{
          padding: '12px 14px', borderRadius: 8,
          background: '#fafaf8', border: '1px solid #ede9e4',
          marginBottom: 20, fontSize: 13, color: '#37352f',
        }}>
          <span style={{ fontWeight: 500, color: '#787671' }}>父批次：</span>
          <span>{isMerge ? (item.predecessor_batches?.join('、') || '无') : (item.batch_no || '无')}</span>
        </div>

        {/* 偏离原因 */}
        {!item.boundary_edge_id && (
          <Form.Item
            name="deviation_reason" label="偏离原因"
            rules={[{ required: true, message: '请输入偏离原因' }]}
          >
            <Input.TextArea rows={2} placeholder="请说明偏离标准路线的具体原因" style={{ borderRadius: 8 }} />
          </Form.Item>
        )}

        {/* 子批次 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: '#37352f', marginBottom: 10 }}>
          {isMerge ? '新批次' : '子批次'}
        </div>
        <Form.List name="children">
          {(fields, { add, remove }) => (
            <div style={{ marginBottom: 8 }}>
              {fields.map(({ key, name, ...rest }) => (
                <div key={key} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 12px', marginBottom: 8,
                  borderRadius: 8, background: '#fafaf8',
                  border: '1px solid #ede9e4',
                }}>
                  <Form.Item {...rest} name={[name, 'batch_no']}
                    rules={[{ required: true, message: '请输入批号' }]}
                    style={{ margin: 0, flex: 2 }}>
                    <Input placeholder="批号" style={{ borderRadius: 6 }} />
                  </Form.Item>
                  <Form.Item {...rest} name={[name, 'quantity']} style={{ margin: 0, flex: 1 }}>
                    <InputNumber placeholder="数量" style={{ width: '100%', borderRadius: 6 }} />
                  </Form.Item>
                  <Form.Item {...rest} name={[name, 'unit']} style={{ margin: 0, flex: 0.8 }}>
                    <Input placeholder="单位" style={{ borderRadius: 6 }} />
                  </Form.Item>
                  {(!isMerge || fields.length > 1) && (
                    <DeleteOutlined onClick={() => remove(name)} style={{ color: '#ff4d4f', cursor: 'pointer' }} />
                  )}
                </div>
              ))}
              {!isMerge && (
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />} style={{ borderRadius: 8 }}>
                  添加子批次
                </Button>
              )}
            </div>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
}
