'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space, Select, Switch } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createSparePart, updateSparePart } from '@/actions/equipment'
import { fetchDepartmentsClient } from '@/lib/api/equipment-client'
import { CreateSparePartInput, UpdateSparePartInput, DepartmentOption } from '@/types/equipment'

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
  const [submitting, setSubmitting] = useState(false)
  const [departments, setDepartments] = useState<DepartmentOption[]>([])
  const { sparePartDrawerOpen, editingSparePart, closeSparePartDrawer } = useEquipmentStore()

  const isEdit = !!editingSparePart

  // ponytail: initialValues handles form seeding declaratively; destroyOnHidden + preserve={false}
  // already remount the form on every open, so useEffect setFieldsValue was redundant.
  const initialValues = editingSparePart
    ? {
        code: editingSparePart.code,
        name: editingSparePart.name,
        specification: editingSparePart.specification,
        unit: editingSparePart.unit,
        category: editingSparePart.category,
        default_supplier: editingSparePart.default_supplier,
        unit_price: editingSparePart.unit_price,
        is_active: editingSparePart.is_active,
      }
    : { is_active: true }

  const handleOpenChange = (open: boolean) => {
    if (open && !isEdit && departments.length === 0) {
      // 归属部门仅在新建时可选；编辑态归属不随主数据修改
      fetchDepartmentsClient()
        .then(depts => { setDepartments(depts) })
        .catch(() => { /* 部门列表拉取失败不阻塞建档 */ })
    }
  }

  const handleSubmit = async () => {
    if (submitting) return
    let values: {
      code: string; name: string; unit: string
      specification?: string; category?: string; default_supplier?: string
      unit_price?: number; department_id?: string; is_active?: boolean
      initial_qty?: number; safety_qty?: number; min_order_qty?: number
      warehouse_location?: string
    }
    try {
      values = await form.validateFields()
    } catch { return }
    // 重复提交会重复建档，加在途状态挡住第二次点击
    setSubmitting(true)
    try {
      if (editingSparePart) {
        const data: UpdateSparePartInput = {
          code: values.code,
          name: values.name,
          specification: values.specification || undefined,
          unit: values.unit,
          category: values.category || undefined,
          default_supplier: values.default_supplier || undefined,
          unit_price: values.unit_price ?? undefined,
          is_active: values.is_active ?? true,
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
          department_id: values.department_id || undefined,
          initial_qty: values.initial_qty ?? 0,
          safety_qty: values.safety_qty ?? 0,
          min_order_qty: values.min_order_qty ?? 1,
          warehouse_location: values.warehouse_location || undefined,
        }
        const result = await createSparePart(data)
        if (!result.success) { message.error(result.error); return }
        const initialQty = values.initial_qty ?? 0
        message.success(
          initialQty > 0
            ? `创建成功，期初库存 ${initialQty} ${values.unit}`
            : '创建成功',
        )
      }
      closeSparePartDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title={isEdit ? '编辑备件' : '新建备件'}
      size={480}
      open={sparePartDrawerOpen}
      onClose={closeSparePartDrawer}
      afterOpenChange={handleOpenChange}
      destroyOnHidden
      styles={{ body: { padding: '16px 24px' } }}
      extra={
        <Space>
          <Button onClick={closeSparePartDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>{isEdit ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false} initialValues={initialValues} key={editingSparePart?.id ?? 'new'}>

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
        {isEdit ? (
          <>
            <Form.Item label="归属部门">
              <Input
                value={editingSparePart?.department_name || ''}
                disabled
                placeholder="未设置"
              />
            </Form.Item>
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          </>
        ) : (
          <>
            <Form.Item
              name="department_id"
              label="归属部门"
              extra={`留空自动关联当前用户部门（${userDepartmentName || '未检测到部门，需手动选择'}）`}
            >
              <Select
                placeholder="自动关联当前用户部门"
                allowClear
                showSearch
                optionFilterProp="label"
                options={departments.map(d => ({ label: d.name, value: d.id }))}
              />
            </Form.Item>
          </>
        )}

        {/* ── 库存设置（仅新建；编辑态走「库存设置」抽屉） ── */}
        {!isEdit && (
          <>
            {sectionLabel('库存设置')}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
              <Form.Item name="initial_qty" label="期初库存" initialValue={0} extra="大于 0 时记一条期初入库流水">
                <InputNumber min={0} precision={0} style={{ width: '100%' }} placeholder="0" />
              </Form.Item>
              <Form.Item name="safety_qty" label="安全库存" initialValue={0} extra="低于该值触发预警">
                <InputNumber min={0} precision={0} style={{ width: '100%' }} placeholder="0" />
              </Form.Item>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
              <Form.Item name="min_order_qty" label="最小采购批量" initialValue={1}>
                <InputNumber min={1} precision={0} style={{ width: '100%' }} placeholder="1" />
              </Form.Item>
              <Form.Item name="warehouse_location" label="库位">
                <Input placeholder="如 A-01（可选）" />
              </Form.Item>
            </div>
          </>
        )}
      </Form>
    </Drawer>
  )
}
