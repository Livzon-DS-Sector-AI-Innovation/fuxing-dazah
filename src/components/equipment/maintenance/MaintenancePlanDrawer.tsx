'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, InputNumber, DatePicker, Button, Space, Radio, TreeSelect } from 'antd'
import dayjs from 'dayjs'
import { useEquipmentStore } from '@/stores/equipment'
import { createMaintenancePlan, updateMaintenancePlan } from '@/actions/equipment'
import { CreateMaintenancePlanInput, UpdateMaintenancePlanInput, EquipmentCategory, Personnel } from '@/types/equipment'
import { PersonnelSelect } from '@/components/equipment'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { fetchCategoriesClient } from '@/lib/api/equipment-client'

const { TextArea } = Input

interface Equipment {
  id: string
  name: string
  equipment_no: string
  responsible_person_id?: string | null
}

interface MaintenancePlanDrawerProps {
  equipments: Equipment[]
  onRefresh?: () => void
}

interface TreeNode {
  title: string
  value: string
  children?: TreeNode[]
}

function toTreeData(categories: EquipmentCategory[]): TreeNode[] {
  return categories.map((c) => ({
    title: `${c.code} - ${c.name}`,
    value: c.id,
    children: c.children ? toTreeData(c.children) : undefined,
  }))
}

export function MaintenancePlanDrawer({ equipments, onRefresh }: MaintenancePlanDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { maintenancePlanDrawerOpen, editingMaintenancePlan, closeMaintenancePlanDrawer } = useEquipmentStore()
  const [personnel, setPersonnel] = useState<Personnel[]>([])
  const [categories, setCategories] = useState<EquipmentCategory[]>([])
  const [planMode, setPlanMode] = useState<'equipment' | 'category'>('equipment')

  useEffect(() => {
    if (!maintenancePlanDrawerOpen) return

    // Load personnel and categories in parallel
    Promise.all([
      fetchPersonnelList({}).then(r => setPersonnel(r.items.filter(p => p.is_active))),
      fetchCategoriesClient().then(setCategories),
    ]).catch(err => console.warn('MaintenancePlanDrawer: 加载数据失败', err))

    // 延迟确保 Form 字段在 destroyOnHidden 后重新挂载完毕
    const timer = setTimeout(() => {
      if (editingMaintenancePlan) {
        // Determine plan mode from existing data
        setPlanMode(editingMaintenancePlan.category_id ? 'category' : 'equipment')
        form.setFieldsValue({
          equipment_id: editingMaintenancePlan.equipment_id || undefined,
          category_id: editingMaintenancePlan.category_id || undefined,
          plan_name: editingMaintenancePlan.plan_name,
          plan_type: editingMaintenancePlan.plan_type,
          frequency: editingMaintenancePlan.frequency,
          frequency_unit: editingMaintenancePlan.frequency_unit,
          last_maintenance_date: editingMaintenancePlan.last_maintenance_date ? dayjs(editingMaintenancePlan.last_maintenance_date) : undefined,
          executor_id: editingMaintenancePlan.executor_id || undefined,
          maintenance_content: editingMaintenancePlan.maintenance_content,
          remark: editingMaintenancePlan.remark,
          status: editingMaintenancePlan.status,
        })
      } else {
        form.resetFields()
        setPlanMode('equipment')
        form.setFieldsValue({ plan_type: '预防性维护', frequency_unit: '月' })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [maintenancePlanDrawerOpen, editingMaintenancePlan, form])

  const handleSubmit = async () => {
    let values: any
    try { values = await form.validateFields() } catch { return }
    if (editingMaintenancePlan) {
      const data: UpdateMaintenancePlanInput = {
        plan_name: values.plan_name,
        plan_type: values.plan_type,
        frequency: values.frequency,
        frequency_unit: values.frequency_unit,
        last_maintenance_date: values.last_maintenance_date ? values.last_maintenance_date.format('YYYY-MM-DD') : undefined,
        executor_id: values.executor_id,
        maintenance_content: values.maintenance_content || undefined,
        remark: values.remark || undefined,
        status: values.status,
      }
      const result = await updateMaintenancePlan(editingMaintenancePlan.id, data)
      if (!result.success) { message.error(result.error); return }
      message.success('更新成功')
    } else {
      const data: CreateMaintenancePlanInput = {
        equipment_id: planMode === 'equipment' ? values.equipment_id : undefined,
        category_id: planMode === 'category' ? values.category_id : undefined,
        plan_name: values.plan_name,
        plan_type: values.plan_type,
        frequency: values.frequency,
        frequency_unit: values.frequency_unit,
        last_maintenance_date: values.last_maintenance_date ? values.last_maintenance_date.format('YYYY-MM-DD') : undefined,
        executor_id: values.executor_id,
        maintenance_content: values.maintenance_content || undefined,
        remark: values.remark || undefined,
      }
      const result = await createMaintenancePlan(data)
      if (!result.success) { message.error(result.error); return }
      message.success('创建成功')
    }
    closeMaintenancePlanDrawer()
    onRefresh?.()
  }

  return (
    <Drawer
      title={editingMaintenancePlan ? '编辑维护计划' : '新建维护计划'}
      size={480}
      open={maintenancePlanDrawerOpen}
      onClose={closeMaintenancePlanDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeMaintenancePlanDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{editingMaintenancePlan ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        {!editingMaintenancePlan && (
          <>
            <Form.Item label="关联方式">
              <Radio.Group
                value={planMode}
                onChange={e => {
                  setPlanMode(e.target.value)
                  form.setFieldsValue({ equipment_id: undefined, category_id: undefined })
                }}
              >
                <Radio.Button value="equipment">按设备</Radio.Button>
                <Radio.Button value="category">按分类</Radio.Button>
              </Radio.Group>
            </Form.Item>
            {planMode === 'equipment' ? (
              <Form.Item name="equipment_id" label="关联设备" rules={[{ required: true, message: '请选择设备' }]}>
                <Select placeholder="选择设备" showSearch optionFilterProp="label"
                  options={equipments.map((eq) => ({ label: `${eq.equipment_no} - ${eq.name}`, value: eq.id }))}
                />
              </Form.Item>
            ) : (
              <Form.Item name="category_id" label="关联分类" rules={[{ required: true, message: '请选择分类' }]}>
                <TreeSelect
                  placeholder="选择分类"
                  treeDefaultExpandAll
                  showSearch
                  filterTreeNode={(input, node) => String(node?.title ?? '').includes(input)}
                  treeData={toTreeData(categories)}
                />
              </Form.Item>
            )}
          </>
        )}
        <Form.Item name="plan_name" label="计划名称" rules={[{ required: true, message: '请输入计划名称' }]}>
          <Input placeholder="请输入计划名称" />
        </Form.Item>
        <Form.Item name="plan_type" label="维护类型" rules={[{ required: true, message: '请选择维护类型' }]}>
          <Select options={[{ label: '预防性维护', value: '预防性维护' }, { label: '预测性维护', value: '预测性维护' }]} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="frequency" label="维护频率" rules={[{ required: true, message: '请输入频率' }]} style={{ flex: 1 }}>
            <InputNumber min={1} max={365} precision={0} style={{ width: '100%' }} placeholder="请输入整数" />
          </Form.Item>
          <Form.Item name="frequency_unit" label="频率单位" rules={[{ required: true, message: '请选择单位' }]} style={{ flex: 1 }}>
            <Select options={[
              { label: '天', value: '天' },
              { label: '周', value: '周' },
              { label: '月', value: '月' },
              { label: '年', value: '年' },
            ]} />
          </Form.Item>
        </div>
        <Form.Item name="last_maintenance_date" label="上次维护日期" rules={[{ required: true, message: '请选择上次维护日期' }]}>
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" placeholder="选择日期" />
        </Form.Item>
        <Form.Item name="executor_id" label="执行人" rules={[{ required: true, message: '请选择执行人' }]}>
          <PersonnelSelect personnel={personnel} placeholder="选择执行人" />
        </Form.Item>
        {editingMaintenancePlan && (
          <Form.Item name="status" label="状态">
            <Select options={[
              { label: '启用', value: '启用' },
              { label: '停用', value: '停用' },
              { label: '已完成', value: '已完成' },
            ]} />
          </Form.Item>
        )}
        <Form.Item name="maintenance_content" label="维护内容">
          <TextArea placeholder="维护内容描述（可选）" rows={4} maxLength={1000} showCount />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="备注信息（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
