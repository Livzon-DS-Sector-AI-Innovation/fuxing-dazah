'use client'

import { App, Form, Input, InputNumber, Modal, Select } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createBatch } from '@/actions/production'
import { fetchRoutesClient } from '@/lib/api/production-client'

interface Props {
  open: boolean
  productId: string
  onClose: () => void
}

export function CreateBatchModal({ open, productId, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  const { data: routes } = useQuery({
    queryKey: ['production-routes', productId],
    queryFn: () => fetchRoutesClient(productId),
    enabled: open,
  })
  const publishedRoutes = routes?.filter(r => r.status === 'published') ?? []

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const result = await createBatch({ ...values, product_id: productId })
    if (result.success) {
      message.success('批次已创建')
      queryClient.invalidateQueries({ queryKey: ['production-batches', productId] })
      form.resetFields()
      onClose()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal title="新建批次" open={open} onOk={handleOk} onCancel={onClose} destroyOnHidden>
      <Form form={form} layout="vertical">
        <Form.Item
          name="batch_no"
          label="批号"
          rules={[{ required: true, message: '请输入批号' }]}
        >
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item
          name="route_id"
          label="工艺路线版本"
          rules={[{ required: true, message: '请选择已发布的工艺路线' }]}
        >
          <Select
            options={publishedRoutes.map(r => ({
              value: r.id,
              label: `V${r.version} · ${r.name}`,
            }))}
            notFoundContent="该产品没有已发布的工艺路线"
          />
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
    </Modal>
  )
}
