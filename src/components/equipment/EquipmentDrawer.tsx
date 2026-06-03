'use client'

import { useState, useEffect } from 'react'
import { App, Drawer, Form, Input, Select, DatePicker, Button, Space } from 'antd'
import dayjs from 'dayjs'
import { useEquipmentStore } from '@/stores/equipment'
import { EquipmentStatus, EquipmentCategory, Location } from '@/types/equipment'
import { createEquipment, updateEquipment } from '@/actions/equipment'

const { TextArea } = Input

const statusOptions: { label: string; value: EquipmentStatus }[] = [
  { label: '在用', value: '在用' },
  { label: '备用', value: '备用' },
  { label: '维修中', value: '维修中' },
  { label: '停用', value: '停用' },
  { label: '报废', value: '报废' },
]

// 扁平化树结构
function flattenCategories(categories: EquipmentCategory[], prefix = ''): { label: string; value: string }[] {
  const result: { label: string; value: string }[] = []
  for (const cat of categories) {
    const label = prefix ? `${prefix} / ${cat.name}` : cat.name
    result.push({ label, value: cat.id })
    if (cat.children?.length) {
      result.push(...flattenCategories(cat.children, label))
    }
  }
  return result
}

function flattenLocations(locations: Location[], prefix = ''): { label: string; value: string }[] {
  const result: { label: string; value: string }[] = []
  for (const loc of locations) {
    const label = prefix ? `${prefix} / ${loc.name}` : loc.name
    result.push({ label, value: loc.id })
    if (loc.children?.length) {
      result.push(...flattenLocations(loc.children, label))
    }
  }
  return result
}

interface EquipmentDrawerProps {
  onRefresh?: () => void
}

export function EquipmentDrawer({ onRefresh }: EquipmentDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)
  const {
    equipmentDrawerOpen,
    editingEquipment,
    closeEquipmentDrawer,
    categories,
    locations,
  } = useEquipmentStore()

  const categoryOptions = flattenCategories(categories)
  const locationOptions = flattenLocations(locations)

  useEffect(() => {
    if (equipmentDrawerOpen) {
      if (editingEquipment) {
        form.setFieldsValue({
          name: editingEquipment.name,
          category_id: editingEquipment.category_id,
          location_id: editingEquipment.location_id,
          status: editingEquipment.status,
          model: editingEquipment.model ?? undefined,
          specification: editingEquipment.specification ?? undefined,
          manufacturer: editingEquipment.manufacturer ?? undefined,
          supplier: editingEquipment.supplier ?? undefined,
          production_date: editingEquipment.production_date ? dayjs(editingEquipment.production_date) : undefined,
          commissioning_date: editingEquipment.commissioning_date ? dayjs(editingEquipment.commissioning_date) : undefined,
          description: editingEquipment.description ?? undefined,
        })
      } else {
        form.resetFields()
      }
    }
  }, [equipmentDrawerOpen, editingEquipment, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const submitData = {
        ...values,
        production_date: values.production_date
          ? values.production_date.format('YYYY-MM-DD')
          : undefined,
        commissioning_date: values.commissioning_date
          ? values.commissioning_date.format('YYYY-MM-DD')
          : undefined,
      }

      if (editingEquipment) {
        await updateEquipment(editingEquipment.id, submitData)
        message.success('更新设备成功')
      } else {
        await createEquipment(submitData)
        message.success('创建设备成功')
      }
      closeEquipmentDrawer()
      onRefresh?.()
    } catch (err: any) {
      // Ant Design validation errors have an errorFields property
      if (err?.errorFields) return
      message.error('操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title={editingEquipment ? '编辑设备' : '新增设备'}
      size={480}
      open={equipmentDrawerOpen}
      onClose={closeEquipmentDrawer}
      destroyOnHidden
      styles={{
        header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
        body: { padding: '24px' },
      }}
      extra={
        <Space>
          <Button onClick={closeEquipmentDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        styles={{ label: { fontWeight: 500, color: '#1a1a1a' } }}
      >
        <Form.Item
          name="name"
          label="设备名称"
          rules={[{ required: true, message: '请输入设备名称' }]}
        >
          <Input placeholder="请输入设备名称" />
        </Form.Item>
        <Form.Item
          name="category_id"
          label="设备分类"
          rules={[{ required: true, message: '请选择设备分类' }]}
        >
          <Select
            placeholder="请选择设备分类"
            showSearch
            optionFilterProp="label"
            options={categoryOptions}
          />
        </Form.Item>
        <Form.Item
          name="location_id"
          label="设备位置"
          rules={[{ required: true, message: '请选择设备位置' }]}
        >
          <Select
            placeholder="请选择设备位置"
            showSearch
            optionFilterProp="label"
            options={locationOptions}
          />
        </Form.Item>
        <Form.Item
          name="status"
          label="设备状态"
          rules={[{ required: true, message: '请选择设备状态' }]}
        >
          <Select placeholder="请选择设备状态" options={statusOptions} />
        </Form.Item>
        <Form.Item name="model" label="设备型号">
          <Input placeholder="请输入设备型号" />
        </Form.Item>
        <Form.Item name="specification" label="设备规格">
          <Input placeholder="请输入设备规格" />
        </Form.Item>
        <Form.Item name="manufacturer" label="制造商">
          <Input placeholder="请输入制造商" />
        </Form.Item>
        <Form.Item name="supplier" label="供应商">
          <Input placeholder="请输入供应商" />
        </Form.Item>
        <Form.Item name="production_date" label="出厂日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="commissioning_date" label="投用日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="description" label="设备描述">
          <TextArea rows={4} placeholder="请输入设备描述" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
