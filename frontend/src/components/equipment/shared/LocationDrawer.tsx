'use client'

import { useState, useEffect } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createLocation, updateLocation } from '@/actions/equipment'

const { TextArea } = Input

export function LocationDrawer({ onRefresh }: { onRefresh?: () => void }) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)
  const {
    locationDrawerOpen,
    editingLocation,
    closeLocationDrawer,
    locations,
  } = useEquipmentStore()

  useEffect(() => {
    if (!locationDrawerOpen) return
    const timer = setTimeout(() => {
      if (editingLocation) {
        form.setFieldsValue({
          name: editingLocation.name,
          code: editingLocation.code,
          parent_id: editingLocation.parent_id ?? undefined,
          description: editingLocation.description ?? undefined,
        })
      } else {
        form.resetFields()
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [locationDrawerOpen, editingLocation, form])

  const handleSubmit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      const result = editingLocation
        ? await updateLocation(editingLocation.id, values)
        : await createLocation(values)
      if (!result.success) {
        message.error(result.error)
        return
      }
      if (editingLocation) {
        message.success('更新位置成功')
      } else {
        message.success('创建位置成功')
      }
      closeLocationDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  // 递归展平位置树，用缩进前缀区分层级
  function flattenTree(
    items: typeof locations,
    excludeId?: string,
    depth = 0,
  ): { label: string; value: string }[] {
    const result: { label: string; value: string }[] = []
    for (const loc of items) {
      if (loc.id === excludeId) {
        if (loc.children?.length) {
          result.push(...flattenTree(loc.children, excludeId, depth))
        }
        continue
      }
      const prefix = depth > 0 ? '  '.repeat(depth) + '└ ' : ''
      result.push({ label: prefix + loc.name, value: loc.id })
      if (loc.children?.length) {
        result.push(...flattenTree(loc.children, excludeId, depth + 1))
      }
    }
    return result
  }

  const parentOptions = flattenTree(locations, editingLocation?.id)

  return (
    <Drawer
      title={editingLocation ? '编辑位置' : '新增位置'}
      size={400}
      open={locationDrawerOpen}
      onClose={closeLocationDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeLocationDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="位置名称"
          rules={[{ required: true, message: '请输入位置名称' }]}
        >
          <Input placeholder="请输入位置名称" />
        </Form.Item>
        <Form.Item
          name="code"
          label="位置代码"
          rules={[{ required: true, message: '请输入位置代码' }]}
        >
          <Input placeholder="请输入位置代码" />
        </Form.Item>
        <Form.Item name="parent_id" label="父位置">
          <Select
            placeholder="请选择父位置（可选）"
            allowClear
            options={parentOptions}
          />
        </Form.Item>
        <Form.Item name="description" label="位置描述">
          <TextArea rows={4} placeholder="请输入位置描述" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
