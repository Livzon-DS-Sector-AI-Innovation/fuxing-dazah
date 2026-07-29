'use client'

import { useEffect, useState } from 'react'
import { Modal, Form, Input, Select, DatePicker, InputNumber, App } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Demand, CreateDemandInput, UpdateDemandInput } from '@/types/production'
import { createDemand, updateDemand } from '@/actions/production'
import { fetchProductsClient } from '@/lib/api/production-client'
import { serializeDates } from './utils'
import dayjs from 'dayjs'

interface Props {
  open: boolean
  demand: Demand | null
  onClose: () => void
}

export function DemandFormModal({ open, demand, onClose }: Props) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const isEdit = !!demand
  const [productKeyword, setProductKeyword] = useState('')

  const { data: products = [] } = useQuery({
    queryKey: ['products', productKeyword],
    queryFn: () => fetchProductsClient(productKeyword || undefined),
    staleTime: 30_000,
  })

  useEffect(() => {
    if (open) {
      if (demand) {
        form.setFieldsValue({
          ...demand,
          demand_date: demand.demand_date ? dayjs(demand.demand_date) : undefined,
        })
      } else {
        form.resetFields()
      }
    }
  }, [open, demand, form])

  const mut = useMutation({
    mutationFn: async (vals: unknown) => {
      const input = serializeDates(vals as Record<string, unknown>)
      if (isEdit) {
        const result = await updateDemand(demand!.id, input as unknown as UpdateDemandInput)
        if (!result.success) throw new Error(result.error)
        return result.data
      }
      const result = await createDemand(input as unknown as CreateDemandInput)
      if (!result.success) throw new Error(result.error)
      return result.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['demands'] })
      message.success(isEdit ? '已更新' : '已创建')
      onClose()
    },
    onError: (err: Error) => {
      message.error(err.message)
    },
  })

  const handleProductSelect = (productId: string) => {
    const p = products.find((prod: { id: string; product_name: string; unit: string }) => prod.id === productId)
    if (p) {
      form.setFieldsValue({ product_name: p.product_name, unit: p.unit || 'kg' })
    }
  }

  return (
    <Modal
      title={isEdit ? '编辑需求' : '新建需求'}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mut.isPending}
      width={560}
    >
      <Form form={form} layout="vertical" onFinish={vals => mut.mutate(vals)}>
        <Form.Item name="demand_no" label="需求编号" rules={[{ required: !isEdit }]}>
          <Input disabled={isEdit} placeholder="留空自动生成" />
        </Form.Item>
        <Form.Item name="source_type" label="来源" initialValue="manual">
          <Select
            options={[
              { value: 'manual', label: '手动录入' },
              { value: 'sales_order', label: '销售订单' },
              { value: 'forecast', label: '预测' },
              { value: 'internal', label: '内部需求' },
            ]}
          />
        </Form.Item>
        <Form.Item name="product_id" label="产品" rules={[{ required: true, message: '请选择产品' }]}>
          <Select
            showSearch={{ onSearch: setProductKeyword, filterOption: false }}
            placeholder="搜索并选择产品"
            onChange={handleProductSelect}
            options={products.map((p: { id: string; product_name: string }) => ({
              value: p.id,
              label: p.product_name,
            }))}
          />
        </Form.Item>
        <Form.Item name="product_name" hidden>
          <Input />
        </Form.Item>
        <Form.Item name="demanded_quantity" label="需求量" rules={[{ required: true }]}>
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="unit" label="单位" rules={[{ required: true }]} initialValue="kg">
          <Input />
        </Form.Item>
        <Form.Item name="demand_date" label="交期" rules={[{ required: true }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="priority" label="优先级" initialValue="medium">
          <Select
            options={[
              { value: 'urgent', label: '紧急' },
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]}
          />
        </Form.Item>
        <Form.Item name="customer_name" label="客户">
          <Input placeholder="临时字段" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
