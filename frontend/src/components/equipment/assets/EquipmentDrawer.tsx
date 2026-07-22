'use client'

import { useState, useEffect, useRef } from 'react'
import { App, Drawer, Form, Input, Select, DatePicker, Button, Space } from 'antd'
import dayjs from 'dayjs'
import { useEquipmentStore } from '@/stores/equipment'
import { EquipmentStatus, RunningStatus, EquipmentImportance, EquipmentCategory, Location } from '@/types/equipment'
import { createEquipment, updateEquipment } from '@/actions/equipment'

const { TextArea } = Input

const importanceOptions: { label: string; value: EquipmentImportance }[] = [
  { label: '高', value: '高' },
  { label: '中', value: '中' },
  { label: '低', value: '低' },
]

const statusOptions: { label: string; value: EquipmentStatus }[] = [
  { label: '完好', value: '完好' },
  { label: '备用', value: '备用' },
  { label: '故障待检', value: '故障待检' },
  { label: '维修中', value: '维修中' },
  { label: '报废', value: '报废' },
]

const runningStatusOptions: { label: string; value: RunningStatus }[] = [
  { label: '开机', value: '开机' },
  { label: '停机', value: '停机' },
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

interface StaffOption {
  id: string
  name: string
  employee_no: string | null
  department: string | null
}

interface EquipmentDrawerProps {
  onRefresh?: () => void
  defaultDepartmentId?: string | null
}

export function EquipmentDrawer({ onRefresh, defaultDepartmentId }: EquipmentDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)
  const [staffKeyword, setStaffKeyword] = useState('')
  const [staffOptions, setStaffOptions] = useState<{ label: string; value: string }[]>([])
  const [staffLoading, setStaffLoading] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const {
    equipmentDrawerOpen,
    editingEquipment,
    closeEquipmentDrawer,
    categories,
    locations,
    departments,
  } = useEquipmentStore()

  const categoryOptions = flattenCategories(categories)
  const locationOptions = flattenLocations(locations)

  // 搜索员工：输入关键字后延迟 300ms 从 identity/personnel 查询
  const handleStaffSearch = (value: string) => {
    setStaffKeyword(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!value.trim()) {
      setStaffOptions([])
      return
    }
    searchTimer.current = setTimeout(async () => {
      setStaffLoading(true)
      try {
        const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
        const params = new URLSearchParams({ limit: '50', keyword: value.trim() })
        const resp = await fetch(`${API_BASE}/api/v1/identity/personnel?${params}`)
        if (!resp.ok) { setStaffOptions([]); return }
        const json = await resp.json()
        const items = (json.data?.items ?? []) as Record<string, unknown>[]
        setStaffOptions(items.map(u => ({
          label: `${String(u.name ?? '')}${u.department ? ` - ${String(u.department)}` : ''}${u.employee_no ? ` (${String(u.employee_no)})` : ''}`,
          value: String(u.id),
        })))
      } catch {
        setStaffOptions([])
      } finally {
        setStaffLoading(false)
      }
    }, 300)
  }

  useEffect(() => {
    if (equipmentDrawerOpen) {
      if (editingEquipment) {
        // 编辑模式：用后端返回的 responsible_person_name 直接构造初始选项
        const initialOptions: { label: string; value: string }[] = []
        if (editingEquipment.responsible_person_id && editingEquipment.responsible_person_name) {
          initialOptions.push({
            label: editingEquipment.responsible_person_name,
            value: editingEquipment.responsible_person_id,
          })
        }
        setStaffOptions(initialOptions)

        form.setFieldsValue({
          name: editingEquipment.name,
          equipment_no: editingEquipment.equipment_no,
          category_ids: editingEquipment.category_ids || [],
          location_id: editingEquipment.location_id,
          status: editingEquipment.status,
          running_status: editingEquipment.running_status,
          model: editingEquipment.model ?? undefined,
          specification: editingEquipment.specification ?? undefined,
          manufacturer: editingEquipment.manufacturer ?? undefined,
          supplier: editingEquipment.supplier ?? undefined,
          production_date: editingEquipment.production_date ? dayjs(editingEquipment.production_date) : undefined,
          commissioning_date: editingEquipment.commissioning_date ? dayjs(editingEquipment.commissioning_date) : undefined,
          description: editingEquipment.description ?? undefined,
          department_id: editingEquipment.department_id ?? undefined,
          responsible_person_id: editingEquipment.responsible_person_id ?? undefined,
          importance: editingEquipment.importance ?? '低',
        })
      } else {
        form.resetFields()
        setStaffOptions([])
        // 新建设备时预填登录用户所在部门，负责人由 handleDepartmentChange 自动填入部门负责人
        if (defaultDepartmentId) {
          form.setFieldsValue({ department_id: defaultDepartmentId })
          handleDepartmentChange(defaultDepartmentId)
        }
      }
    }
  }, [equipmentDrawerOpen, editingEquipment, form])

  // 选择部门后自动填入负责人（默认为部门负责人，但可手动修改）
  const handleDepartmentChange = (deptId: string | undefined) => {
    if (!deptId) {
      form.setFieldsValue({ responsible_person_id: undefined })
      return
    }
    const dept = departments.find(d => d.id === deptId)
    if (dept?.leader_id) {
      form.setFieldsValue({ responsible_person_id: dept.leader_id })
      // 使用 functional updater 避免 stale closure：始终替换 leader 选项
      setStaffOptions(prev => {
        const label = `${dept.leader_name ?? ''}${dept.name ? ` - ${dept.name}` : ''}`
        return [...prev.filter(o => o.value !== dept.leader_id), { label, value: dept.leader_id! }]
      })
    } else {
      form.setFieldsValue({ responsible_person_id: undefined })
    }
  }

  const handleSubmit = async () => {
    let values: any
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      const submitData = {
        ...values,
        production_date: values.production_date
          ? values.production_date.format('YYYY-MM-DD')
          : undefined,
        commissioning_date: values.commissioning_date
          ? values.commissioning_date.format('YYYY-MM-DD')
          : undefined,
      }

      const result = editingEquipment
        ? await updateEquipment(editingEquipment.id, submitData)
        : await createEquipment(submitData)
      if (!result.success) {
        message.error(result.error)
        return
      }
      if (editingEquipment) {
        message.success('更新设备成功')
      } else {
        message.success('创建设备成功')
      }
      closeEquipmentDrawer()
      onRefresh?.()
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
      maskClosable={false}
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
          name="equipment_no"
          label="设备编号"
          rules={[{ required: true, message: '请输入设备编号' }]}
        >
          <Input placeholder="请输入唯一设备编号" disabled={!!editingEquipment} />
        </Form.Item>
        <Form.Item
          name="category_ids"
          label="设备分类"
          rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一个设备分类' }]}
        >
          <Select
            mode="multiple"
            placeholder="请选择设备分类（支持多选）"
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
        <Form.Item name="department_id" label="归属部门">
          <Select
            placeholder="请选择归属部门"
            allowClear
            showSearch
            optionFilterProp="label"
            options={departments.map(d => ({ label: d.name, value: d.id }))}
            onChange={handleDepartmentChange}
          />
        </Form.Item>
        <Form.Item name="responsible_person_id" label="负责人">
          <Select
            placeholder="选择部门后默认填入部门负责人，也可搜索修改"
            allowClear
            showSearch
            filterOption={false}
            onSearch={handleStaffSearch}
            loading={staffLoading}
            notFoundContent={staffLoading ? '搜索中...' : staffKeyword ? '无匹配人员' : '输入姓名搜索员工'}
            options={staffOptions}
          />
        </Form.Item>
        <Form.Item
          name="status"
          label="设备状态"
          rules={[{ required: true, message: '请选择设备状态' }]}
        >
          <Select placeholder="请选择设备状态" options={statusOptions} />
        </Form.Item>
        <Form.Item
          name="running_status"
          label="运行状态"
          initialValue="开机"
          rules={[{ required: true, message: '请选择运行状态' }]}
        >
          <Select placeholder="请选择运行状态" options={runningStatusOptions} />
        </Form.Item>
        <Form.Item
          name="importance"
          label="设备重要性"
          rules={[{ required: true, message: '请选择设备重要性' }]}
        >
          <Select placeholder="请选择设备重要性" options={importanceOptions} />
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