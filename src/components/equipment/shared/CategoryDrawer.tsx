'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEffect } from 'react'
import { useEquipmentStore } from '@/stores/equipment'
import { createCategory, updateCategory } from '@/actions/equipment'

const { TextArea } = Input

export function CategoryDrawer({ onRefresh }: { onRefresh?: () => void }) {
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
    if (!categoryDrawerOpen) return
    const timer = setTimeout(() => {
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
    }, 0)
    return () => clearTimeout(timer)
  }, [categoryDrawerOpen, editingCategory, form])

  const handleSubmit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      const result = editingCategory
        ? await updateCategory(editingCategory.id, values)
        : await createCategory(values)
      if (!result.success) {
        message.error(result.error)
        return
      }
      if (editingCategory) {
        message.success('更新分类成功')
      } else {
        message.success('创建分类成功')
      }
      closeCategoryDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  // 递归展平分类树，用缩进前缀区分层级
  function flattenTree(
    items: typeof categories,
    excludeId?: string,
    depth = 0,
  ): { label: string; value: string }[] {
    const result: { label: string; value: string }[] = []
    for (const cat of items) {
      if (cat.id === excludeId) {
        // 编辑时排除自身（避免循环引用），但仍递归处理其子节点
        if (cat.children?.length) {
          result.push(...flattenTree(cat.children, excludeId, depth))
        }
        continue
      }
      const prefix = depth > 0 ? '  '.repeat(depth) + '└ ' : ''
      result.push({ label: prefix + cat.name, value: cat.id })
      if (cat.children?.length) {
        result.push(...flattenTree(cat.children, excludeId, depth + 1))
      }
    }
    return result
  }

  const parentOptions = flattenTree(categories, editingCategory?.id)

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
