'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEffect } from 'react'
import { useEquipmentStore } from '@/stores/equipment'
import { createCategory, updateCategory } from '@/actions/equipment'

const { TextArea } = Input

export function CategoryDrawer() {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)
  const {
    categoryDrawerOpen,
    editingCategory,
    closeCategoryDrawer,
    categories,
  } = useEquipmentStore()

  useEffect(() => {
    if (categoryDrawerOpen) {
      if (editingCategory) {
        form.setFieldsValue({
          name: editingCategory.name,
          code: editingCategory.code,
          parent_id: editingCategory.parent_id ?? undefined,
          description: editingCategory.description ?? undefined,
        })
      } else {
        form.resetFields()
      }
    }
  }, [categoryDrawerOpen, editingCategory, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      if (editingCategory) {
        await updateCategory(editingCategory.id, values)
        message.success('更新分类成功')
      } else {
        await createCategory(values)
        message.success('创建分类成功')
      }
      closeCategoryDrawer()
    } catch (err: any) {
      // Ant Design validation errors have an errorFields property
      if (err?.errorFields) return
      message.error('操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const parentOptions = categories
    .filter((cat) => cat.id !== editingCategory?.id)
    .map((cat) => ({
      label: cat.name,
      value: cat.id,
    }))

  return (
    <Drawer
      title={editingCategory ? '编辑分类' : '新增分类'}
      size={400}
      open={categoryDrawerOpen}
      onClose={closeCategoryDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeCategoryDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="分类名称"
          rules={[{ required: true, message: '请输入分类名称' }]}
        >
          <Input placeholder="请输入分类名称" />
        </Form.Item>
        <Form.Item
          name="code"
          label="分类代码"
          rules={[{ required: true, message: '请输入分类代码' }]}
        >
          <Input placeholder="请输入分类代码" />
        </Form.Item>
        <Form.Item name="parent_id" label="父分类">
          <Select
            placeholder="请选择父分类（可选）"
            allowClear
            options={parentOptions}
          />
        </Form.Item>
        <Form.Item name="description" label="分类描述">
          <TextArea rows={4} placeholder="请输入分类描述" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
