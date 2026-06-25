'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, InputNumber, Switch, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createSparePart, updateSparePart } from '@/actions/equipment'
import { CreateSparePartInput, UpdateSparePartInput } from '@/types/equipment'

interface SparePartDrawerProps {
  onRefresh?: () => void
}

export function SparePartDrawer({ onRefresh }: SparePartDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { sparePartDrawerOpen, editingSparePart, closeSparePartDrawer } = useEquipmentStore()

  useEffect(() => {
    if (sparePartDrawerOpen) {
      if (editingSparePart) {
        form.setFieldsValue({
          code: editingSparePart.code,
          name: editingSparePart.name,
          specification: editingSparePart.specification,
          unit: editingSparePart.unit,
          category: editingSparePart.category,
          default_supplier: editingSparePart.default_supplier,
          unit_price: editingSparePart.unit_price,
          is_active: editingSparePart.is_active,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ is_active: true })
      }
    }
  }, [sparePartDrawerOpen, editingSparePart, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingSparePart) {
        const data: UpdateSparePartInput = {
          code: values.code,
          name: values.name,
          specification: values.specification || undefined,
          unit: values.unit,
          category: values.category || undefined,
          default_supplier: values.default_supplier || undefined,
          unit_price: values.unit_price ?? undefined,
          is_active: values.is_active,
        }
        await updateSparePart(editingSparePart.id, data)
        message.success('更新成功')
      } else {
        const data: CreateSparePartInput = {
          code: values.code,
          name: values.name,
          specification: values.specification || undefined,
          unit: values.unit,
          category: values.category || undefined,
          default_supplier: values.default_supplier || undefined,
          unit_price: values.unit_price ?? undefined,
          is_active: values.is_active,
        }
        await createSparePart(data)
        message.success('创建成功')
      }
      closeSparePartDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title={editingSparePart ? '编辑备件' : '新建备件'}
      size={480}
      open={sparePartDrawerOpen}
      onClose={closeSparePartDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeSparePartDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{editingSparePart ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="code" label="备件编码" rules={[{ required: true, message: '请输入备件编码' }]}>
          <Input placeholder="请输入备件编码" />
        </Form.Item>
        <Form.Item name="name" label="备件名称" rules={[{ required: true, message: '请输入备件名称' }]}>
          <Input placeholder="请输入备件名称" />
        </Form.Item>
        <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}>
          <Input placeholder="请输入单位（如：个、件、套）" />
        </Form.Item>
        <Form.Item name="specification" label="规格型号">
          <Input placeholder="请输入规格型号（可选）" />
        </Form.Item>
        <Form.Item name="category" label="分类">
          <Input placeholder="请输入分类（可选）" />
        </Form.Item>
        <Form.Item name="default_supplier" label="默认供应商">
          <Input placeholder="请输入默认供应商（可选）" />
        </Form.Item>
        <Form.Item name="unit_price" label="单价">
          <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="请输入单价（可选）" prefix="¥" />
        </Form.Item>
        <Form.Item name="is_active" label="状态" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
