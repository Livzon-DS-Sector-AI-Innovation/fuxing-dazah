'use client'

import { App, Form, Input, Modal } from 'antd'
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { createProduct, updateProduct } from '@/actions/production'
import type { Product } from '@/types/production'

interface Props {
  open: boolean
  product: Product | null // null = 新建
  onClose: () => void
}

export function ProductFormModal({ open, product, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (open) {
      form.setFieldsValue(
        product ?? { product_code: '', product_name: '', unit: 'kg', remark: '' },
      )
    }
  }, [open, product, form])

  const handleOk = async () => {
    const values = await form.validateFields()
    const result = product
      ? await updateProduct(product.id, values)
      : await createProduct(values)
    if (result.success) {
      message.success(product ? '产品已更新' : '产品已创建')
      queryClient.invalidateQueries({ queryKey: ['production-products'] })
      onClose()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={product ? '编辑产品' : '新建产品'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="product_code"
          label="产品编码（可选）"
        >
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item
          name="product_name"
          label="产品名称"
          rules={[{ required: true, message: '请输入产品名称' }]}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="unit" label="计量单位">
          <Input maxLength={20} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
