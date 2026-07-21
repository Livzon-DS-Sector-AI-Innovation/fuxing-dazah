'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createSparePart, updateSparePart } from '@/actions/equipment'
import { CreateSparePartInput, UpdateSparePartInput } from '@/types/equipment'

// ── 表单区块标题 ──
const sectionLabel = (text: string) => (
  <div style={{
    fontSize: 11, fontWeight: 600, color: '#a4a097',
    textTransform: 'uppercase', letterSpacing: 1,
    marginBottom: 12, paddingBottom: 8,
    borderBottom: '1px solid #ede9e4',
  }}>
    {text}
  </div>
)

interface SparePartDrawerProps {
  onRefresh?: () => void
  userDepartmentName?: string | null
}

export function SparePartDrawer({ onRefresh, userDepartmentName }: SparePartDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { sparePartDrawerOpen, editingSparePart, closeSparePartDrawer } = useEquipmentStore()

  const isEdit = !!editingSparePart

  useEffect(() => {
    if (!sparePartDrawerOpen) return
    if (editingSparePart) {
      form.setFieldsValue({
        code: editingSparePart.code,
        name: editingSparePart.name,
        specification: editingSparePart.specification,
        unit: editingSparePart.unit,
        category: editingSparePart.category,
        default_supplier: editingSparePart.default_supplier,
        unit_price: editingSparePart.unit_price,
      })
    } else {
      form.resetFields()
    }
  }, [sparePartDrawerOpen, editingSparePart, form])

  const handleSubmit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch { return }
    if (editingSparePart) {
      const data: UpdateSparePartInput = {
        code: values.code,
        name: values.name,
        specification: values.specification || undefined,
        unit: values.unit,
        category: values.category || undefined,
        default_supplier: values.default_supplier || undefined,
        unit_price: values.unit_price ?? undefined,
      }
      const result = await updateSparePart(editingSparePart.id, data)
      if (!result.success) { message.error(result.error); return }
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
      }
      const result = await createSparePart(data)
      if (!result.success) { message.error(result.error); return }
      message.success('创建成功')
    }
    closeSparePartDrawer()
    onRefresh?.()
  }

  return (
    <Drawer
      title={isEdit ? '编辑备件' : '新建备件'}
      size={480}
      open={sparePartDrawerOpen}
      onClose={closeSparePartDrawer}
      destroyOnHidden
      styles={{ body: { padding: '16px 24px' } }}
      extra={
        <Space>
          <Button onClick={closeSparePartDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{isEdit ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>

        {/* ── 基本信息 ── */}
        {sectionLabel('基本信息')}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <Form.Item name="code" label="备件编码" rules={[{ required: true, message: '请输入备件编码' }]}>
            <Input placeholder="请输入备件编码" />
          </Form.Item>
          <Form.Item name="name" label="备件名称" rules={[{ required: true, message: '请输入备件名称' }]}>
            <Input placeholder="请输入备件名称" />
          </Form.Item>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}>
            <Input placeholder="个、件、套…" />
          </Form.Item>
          <Form.Item name="specification" label="规格型号">
            <Input placeholder="规格型号（可选）" />
          </Form.Item>
        </div>

        {/* ── 分类与采购 ── */}
        {sectionLabel('分类与采购')}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <Form.Item name="category" label="分类">
            <Input placeholder="分类（可选）" />
          </Form.Item>
          <Form.Item name="default_supplier" label="默认供应商">
            <Input placeholder="默认供应商（可选）" />
          </Form.Item>
        </div>
        <Form.Item name="unit_price" label="单价">
          <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="单价（可选）" prefix="¥" />
        </Form.Item>

        {/* ── 归属 ── */}
        {sectionLabel('归属')}
        <Form.Item label="归属部门">
          <Input
            value={isEdit ? (editingSparePart?.department_name || '') : (userDepartmentName || '')}
            disabled
            placeholder="自动关联当前用户部门"
          />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
