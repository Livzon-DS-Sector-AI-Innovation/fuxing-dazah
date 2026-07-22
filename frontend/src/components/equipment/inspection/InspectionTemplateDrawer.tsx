'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, Switch, Tooltip } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import { useEquipmentStore } from '@/stores/equipment'
import { createInspectionTemplate, updateInspectionTemplate } from '@/actions/equipment'
import { fetchInspectionTemplateByIdClient } from '@/lib/api/equipment-client'
import { CreateInspectionTemplateInput, UpdateInspectionTemplateInput, InspectionTemplate } from '@/types/equipment'

const C = { navy: '#0a1530', purple: '#5645d4', slate: '#5d5b54', stone: '#a4a097', hairline: '#e5e3df', hairlineSoft: '#ede9e4', surface: '#f6f5f4', surfaceSoft: '#fafaf9', canvas: '#ffffff' }

interface Props { categories: { id: string; name: string }[]; onRefresh?: () => void }

export function InspectionTemplateDrawer({ categories, onRefresh }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { inspectionTemplateDrawerOpen, editingInspectionTemplate, closeInspectionTemplateDrawer } = useEquipmentStore()
  const [liveTemplate, setLiveTemplate] = useState<InspectionTemplate | null>(null)
  const isNew = !editingInspectionTemplate
  const count = liveTemplate?.items_count ?? editingInspectionTemplate?.items_count ?? 0
  const canEnable = !isNew && count > 0

  useEffect(() => {
    if (inspectionTemplateDrawerOpen && editingInspectionTemplate) {
      fetchInspectionTemplateByIdClient(editingInspectionTemplate.id).then(setLiveTemplate).catch(() => setLiveTemplate(editingInspectionTemplate))
    } else setLiveTemplate(null)
  }, [inspectionTemplateDrawerOpen, editingInspectionTemplate])

  useEffect(() => {
    if (inspectionTemplateDrawerOpen) {
      if (editingInspectionTemplate) form.setFieldsValue({ name: editingInspectionTemplate.name, description: editingInspectionTemplate.description ?? undefined, equipment_category_id: editingInspectionTemplate.equipment_category_id ?? undefined, is_active: editingInspectionTemplate.is_active })
      else form.setFieldsValue({ is_active: false })
    }
  }, [inspectionTemplateDrawerOpen, editingInspectionTemplate, form])

  const handleSubmit = async () => {
    let v: any
    try {
      v = await form.validateFields()
    } catch { return }
    if (editingInspectionTemplate) {
      const result = await updateInspectionTemplate(editingInspectionTemplate.id, { name: v.name, description: v.description || undefined, equipment_category_id: v.equipment_category_id || undefined, is_active: v.is_active })
      if (!result.success) { message.error(result.error); return }
      message.success('更新成功')
    } else {
      const result = await createInspectionTemplate({ name: v.name, description: v.description || undefined, equipment_category_id: v.equipment_category_id || undefined, is_active: false })
      if (!result.success) { message.error(result.error); return }
      message.success('创建成功')
    }
    closeInspectionTemplateDrawer(); onRefresh?.()
  }

  return (
    <Drawer title={null} size={460} open={inspectionTemplateDrawerOpen} onClose={closeInspectionTemplateDrawer} destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}>
      <div style={{ background: C.navy, padding: '18px 28px', borderBottom: `3px solid ${C.purple}` }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>Template {isNew ? 'Creation' : 'Settings'}</div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>{isNew ? '新建巡检模板' : '编辑巡检模板'}</div>
      </div>
      <div style={{ padding: '24px 28px 100px' }}>
        <Form form={form} layout="vertical" requiredMark={false}>
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <FileTextOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>模板名称</span>
            </div>
            <Form.Item name="name" noStyle rules={[{ required: true, message: '请输入模板名称' }]}>
              <Input placeholder="如：反应釜巡检模板" style={{ borderRadius: 8, height: 42 }} />
            </Form.Item>
          </div>
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>描述</span>
              <span style={{ fontSize: 11, color: C.stone }}>（选填）</span>
            </div>
            <Form.Item name="description" noStyle>
              <Input.TextArea rows={3} maxLength={500} showCount placeholder="模板描述" style={{ borderRadius: 8 }} />
            </Form.Item>
          </div>
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>设备分类</span>
              <span style={{ fontSize: 11, color: C.stone }}>（选填）</span>
            </div>
            <Form.Item name="equipment_category_id" noStyle>
              <Select placeholder="选择设备分类" allowClear showSearch optionFilterProp="label"
                options={categories.map(c => ({ label: c.name, value: c.id }))} style={{ borderRadius: 8 }} />
            </Form.Item>
          </div>
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>启用状态</span>
            </div>
            <Form.Item name="is_active" noStyle valuePropName="checked">
              {canEnable ? <Switch checkedChildren="启用" unCheckedChildren="停用" style={{ borderRadius: 6 }} />
                : <Tooltip title={isNew ? '新建模板需先保存并添加检查项后启用' : '请先添加至少一个检查项再启用'}><Switch checkedChildren="启用" unCheckedChildren="停用" disabled checked={false} /></Tooltip>}
            </Form.Item>
            {!canEnable && <div style={{ fontSize: 11, color: C.stone, marginTop: 4 }}>{isNew ? '💡 创建后请在「检查项管理」中添加检查项目' : `当前 ${count} 个检查项，至少需要 1 个才能启用`}</div>}
          </div>
        </Form>
      </div>
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '14px 24px', background: C.canvas, borderTop: `1px solid ${C.hairline}`, display: 'flex', gap: 10, justifyContent: 'flex-end', boxShadow: '0 -4px 16px rgba(0,0,0,0.06)' }}>
        <button onClick={closeInspectionTemplateDrawer} style={{ padding: '10px 20px', background: 'transparent', color: C.slate, border: `1px solid ${C.hairline}`, borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}>取消</button>
        <button onClick={handleSubmit} style={{ padding: '10px 28px', background: C.purple, color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', boxShadow: '0 2px 8px rgba(86,69,212,0.3)' }}>{isNew ? '创建模板' : '保存修改'}</button>
      </div>
    </Drawer>
  )
}
