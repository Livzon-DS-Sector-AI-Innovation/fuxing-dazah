'use client'

import { useEffect, useState, useCallback } from 'react'
import { App, Drawer, Button, Table, Form, Input, InputNumber, Select, Typography, Empty, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SaveOutlined, CloseOutlined, OrderedListOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useEquipmentStore } from '@/stores/equipment'
import { createInspectionTemplateItem, updateInspectionTemplateItem, deleteInspectionTemplateItem } from '@/actions/equipment'
import { fetchInspectionTemplateByIdClient } from '@/lib/api/equipment-client'
import { linkPrimary, linkDanger } from '@/components/equipment/shared/shared-styles'
import type { InspectionTemplateItem } from '@/types/equipment'

const { Text } = Typography
const C = { navy: '#0a1530', purple: '#5645d4', ink: '#1a1a1a', slate: '#5d5b54', stone: '#a4a097', hairline: '#e5e3df', hairlineSoft: '#ede9e4', surface: '#f6f5f4', surfaceSoft: '#fafaf9', canvas: '#ffffff' }

interface ItemFormValues { item_name: string; item_description: string; expected_result: string; check_method: string; data_type: string; unit: string; sort_order: number }

function ItemForm({ mode, templateId, itemsCount, initialValues, onSuccess, onCancel }: {
  mode: 'create' | string; templateId: string; itemsCount: number; initialValues?: ItemFormValues; onSuccess: () => void; onCancel: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<ItemFormValues>()
  const [s, setS] = useState(false)
  const watchDataType = Form.useWatch('data_type', form)
  useEffect(() => {
    if (mode === 'create') { form.resetFields(); form.setFieldsValue({ sort_order: itemsCount, item_name: '', item_description: '', expected_result: '', check_method: '', data_type: 'numeric', unit: '' }) }
    else if (initialValues) form.setFieldsValue(initialValues)
  }, [mode, itemsCount, initialValues, form])

  const submit = async () => {
    let v: any
    try {
      v = await form.validateFields()
    } catch { return }
    setS(true)
    try {
      const data = { item_name: v.item_name, item_description: v.item_description || undefined, expected_result: v.expected_result || undefined, check_method: v.check_method || undefined, data_type: v.data_type || 'numeric', unit: v.data_type === 'numeric' ? (v.unit || undefined) : undefined, sort_order: v.sort_order }
      const result = mode === 'create'
        ? await createInspectionTemplateItem(templateId, data)
        : await updateInspectionTemplateItem(mode, data)
      if (!result.success) { message.error(result.error); return }
      message.success(mode === 'create' ? '已添加' : '已更新')
      onSuccess()
    } finally { setS(false) }
  }

  return (
    <div style={{ marginBottom: 16, padding: 16, background: C.surfaceSoft, borderRadius: 10, border: `1px solid ${C.hairline}` }}>
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 12, color: C.ink }}>{mode === 'create' ? '新增检查项' : '编辑检查项'}</Text>
      <Form form={form} layout="vertical" requiredMark={false}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <Form.Item name="item_name" label="检查项名称" rules={[{ required: true, message: '请输入' }]}><Input placeholder="如：温度检查" style={{ borderRadius: 8 }} /></Form.Item>
          <Form.Item name="sort_order" label="排序"><InputNumber min={0} style={{ width: '100%', borderRadius: 8 }} /></Form.Item>
          <Form.Item name="data_type" label="数据类型" rules={[{ required: true, message: '请选择' }]}>
            <Select options={[{ label: '文本', value: 'text' }, { label: '数值', value: 'numeric' }]} style={{ borderRadius: 8 }} />
          </Form.Item>
          {watchDataType === 'numeric' && (
            <Form.Item name="unit" label="单位"><Input placeholder="如：℃、MPa、A" style={{ borderRadius: 8 }} /></Form.Item>
          )}
          <Form.Item name="item_description" label="描述"><Input placeholder="检查项描述" style={{ borderRadius: 8 }} /></Form.Item>
          <Form.Item name="expected_result" label="预期结果"><Input placeholder="如：20-30℃之间" style={{ borderRadius: 8 }} /></Form.Item>
          <Form.Item name="check_method" label="检查方法"><Input placeholder="如：目视/仪表读数" style={{ borderRadius: 8 }} /></Form.Item>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onCancel} style={{ padding: '8px 16px', background: 'transparent', color: C.slate, border: `1px solid ${C.hairline}`, borderRadius: 8, fontSize: 12, fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}>取消</button>
          <button onClick={submit} disabled={s} style={{ padding: '8px 20px', background: C.purple, color: '#fff', border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
            {mode === 'create' ? '添加' : '保存'}
          </button>
        </div>
      </Form>
    </div>
  )
}

export function InspectionItemDrawer() {
  const { message } = App.useApp()
  const { inspectionItemDrawerOpen, inspectionItemTemplateId, editingInspectionItem, closeInspectionItemDrawer } = useEquipmentStore()
  const [items, setItems] = useState<InspectionTemplateItem[]>([])
  const [loading, setLoading] = useState(false)
  const [formMode, setFormMode] = useState<'create' | string | null>(null)
  const [editingData, setEditingData] = useState<InspectionTemplateItem | null>(null)

  const load = useCallback(async () => {
    if (!inspectionItemTemplateId) return; setLoading(true)
    try { const d = await fetchInspectionTemplateByIdClient(inspectionItemTemplateId); setItems(d.items || []) }
    catch { message.error('加载失败') } finally { setLoading(false) }
  }, [inspectionItemTemplateId, message])

  useEffect(() => {
    if (inspectionItemDrawerOpen && inspectionItemTemplateId) { load(); if (editingInspectionItem) { setEditingData(editingInspectionItem); setFormMode(editingInspectionItem.id) } else { setFormMode(null); setEditingData(null) } }
  }, [inspectionItemDrawerOpen, inspectionItemTemplateId, editingInspectionItem, load])

  const close = () => { setFormMode(null); closeInspectionItemDrawer() }
  const startEdit = (item: InspectionTemplateItem) => { setEditingData(item); setFormMode(item.id) }
  const cancelEdit = () => { setFormMode(null); setEditingData(null) }
  const onFormSuccess = () => { setFormMode(null); setEditingData(null); load() }
  const handleDelete = async (item: InspectionTemplateItem) => {
    const result = await deleteInspectionTemplateItem(item.id)
    if (!result.success) { message.error(result.error); return }
    message.success('已删除')
    await load()
  }

  const editInit: ItemFormValues | undefined = editingData && formMode === editingData.id ? {
    item_name: editingData.item_name, item_description: editingData.item_description || '', expected_result: editingData.expected_result || '', check_method: editingData.check_method || '', data_type: editingData.data_type || 'numeric', unit: editingData.unit || '', sort_order: editingData.sort_order,
  } : undefined

  const cols: ColumnsType<InspectionTemplateItem> = [
    { title: '#', dataIndex: 'sort_order', width: 44 },
    { title: '检查项名称', dataIndex: 'item_name', width: 140, render: (n: string) => <Text strong style={{ fontSize: 13 }}>{n}</Text> },
    { title: '类型', dataIndex: 'data_type', width: 72,
      render: (v: string) => v === 'numeric'
        ? <span style={{ padding: '1px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: '#e6e0f5', color: '#5645d4' }}>数值</span>
        : <span style={{ fontSize: 11, color: C.stone }}>文本</span> },
    { title: '单位', dataIndex: 'unit', width: 64, render: (v: string | null) => v || <span style={{ color: C.stone }}>—</span> },
    { title: '描述', dataIndex: 'item_description', width: 120, render: (v: string | null) => v || <span style={{ color: C.stone }}>—</span> },
    { title: '预期结果', dataIndex: 'expected_result', width: 120, render: (v: string | null) => v || <span style={{ color: C.stone }}>—</span> },
    { title: '检查方法', dataIndex: 'check_method', width: 100, render: (v: string | null) => v || <span style={{ color: C.stone }}>—</span> },
    { title: '操作', key: 'a', width: 120, fixed: 'end' as const,
      render: (_: unknown, r: InspectionTemplateItem) => (
        <div style={{ display: 'flex', gap: 10 }}>
          <span role="button" onClick={() => startEdit(r)} style={linkPrimary}><EditOutlined />编辑</span>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}>
            <span role="button" style={linkDanger}><DeleteOutlined />删除</span>
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <Drawer title={null} size={780} open={inspectionItemDrawerOpen} onClose={close} destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}>
      <div style={{ background: C.navy, padding: '16px 28px', borderBottom: `3px solid ${C.purple}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>Checklist Items</div>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>管理检查项</div>
        </div>
        {formMode !== 'create' && (
          <button onClick={() => setFormMode('create')} style={{ padding: '8px 16px', background: 'rgba(255,255,255,0.12)', color: '#fff', border: '1px solid rgba(255,255,255,0.2)', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', gap: 6 }}>
            <PlusOutlined />添加检查项
          </button>
        )}
      </div>
      <div style={{ padding: '20px 28px 40px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <OrderedListOutlined style={{ color: C.purple, fontSize: 14 }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: C.ink }}>检查项列表</span>
          <span style={{ fontSize: 11, color: C.stone }}>共 {items.length} 项</span>
        </div>

        {formMode && <ItemForm mode={formMode} templateId={inspectionItemTemplateId!} itemsCount={items.length} initialValues={formMode !== 'create' ? editInit : undefined} onSuccess={onFormSuccess} onCancel={cancelEdit} />}

        {items.length === 0 && !loading ? <Empty description="暂无检查项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          : <Table columns={cols} dataSource={items} rowKey="id" size="small" loading={loading} pagination={false} scroll={{ x: 'max-content' }} locale={{ emptyText: '暂无检查项' }} />}
      </div>
    </Drawer>
  )
}
