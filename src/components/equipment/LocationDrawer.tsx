'use client'

import { useState, useEffect } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createLocation, updateLocation } from '@/actions/equipment'

const { TextArea } = Input

export function LocationDrawer() {
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
    if (locationDrawerOpen) {
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
    }
  }, [locationDrawerOpen, editingLocation, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      if (editingLocation) {
        await updateLocation(editingLocation.id, values)
        message.success('更新位置成功')
      } else {
        await createLocation(values)
        message.success('创建位置成功')
      }
      closeLocationDrawer()
    } catch (err: any) {
      // Ant Design validation errors have an errorFields property
      if (err?.errorFields) return
      message.error('操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const parentOptions = locations
    .filter((loc) => loc.id !== editingLocation?.id)
    .map((loc) => ({
      label: loc.name,
      value: loc.id,
    }))

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
