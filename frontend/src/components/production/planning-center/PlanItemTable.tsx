'use client'

import { useState, useEffect } from 'react'
import {
  App,
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { createPlanItem, updatePlanItem, deletePlanItem, schedulePlanItem } from '@/actions/production'
import type { PlanItem } from '@/types/production'
import { fetchIntermediateTypesClient } from '@/lib/api/production-client'
import { ITEM_STATUS_CONFIG, PRIORITY_CONFIG } from './constants'
import dayjs from 'dayjs'

const { Text } = Typography

interface Props {
  planOrderId: string
  planOrderStatus: string
  items: PlanItem[]
  isLoading?: boolean
  onRefresh: () => void
}

export function PlanItemTable({ planOrderId, planOrderStatus, items, isLoading = false, onRefresh }: Props) {
  const { message, modal } = App.useApp()
  const [addOpen, setAddOpen] = useState(false)
  const [editItem, setEditItem] = useState<PlanItem | null>(null)
  const [scheduleItem, setScheduleItem] = useState<PlanItem | null>(null)
  const [intermediateTypeKeyword, setIntermediateTypeKeyword] = useState('')
  const [addForm] = Form.useForm()
  const [editForm] = Form.useForm()
  const [scheduleForm] = Form.useForm()
  const canEdit = planOrderStatus === 'draft'

  const { data: intermediateTypeData } = useQuery({
    queryKey: ['intermediate-types', intermediateTypeKeyword],
    queryFn: () => fetchIntermediateTypesClient({ keyword: intermediateTypeKeyword || undefined }),
    staleTime: 30_000,
  })
  const intermediateTypes = intermediateTypeData?.items ?? []

  const handleAdd = async () => {
    const values = await addForm.validateFields().catch(() => null)
    if (!values) return
    const r = await createPlanItem(planOrderId, values)
    if (r.success) {
      message.success('已添加计划项')
      setAddOpen(false)
      addForm.resetFields()
      onRefresh()
    } else {
      message.error(r.error)
    }
  }

  const handleEdit = async () => {
    const values = await editForm.validateFields().catch(() => null)
    if (!values || !editItem) return
    const r = await updatePlanItem(editItem.id, values)
    if (r.success) {
      message.success('已更新')
      setEditItem(null)
      onRefresh()
    } else {
      message.error(r.error)
    }
  }

  const handleDelete = (item: PlanItem) => {
    modal.confirm({
      title: `删除计划项「${item.intermediate_type_name}」?`,
      content: '删除后不可恢复。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const r = await deletePlanItem(item.id)
        if (r.success) {
          message.success('已删除')
          onRefresh()
        } else {
          message.error(r.error)
        }
      },
    })
  }

  const openEditModal = (item: PlanItem) => {
    setEditItem(item)
  }

  const handleSchedule = async () => {
    const values = await scheduleForm.validateFields().catch(() => null)
    if (!values || !scheduleItem) return
    const r = await schedulePlanItem(scheduleItem.id, {
      planned_start: values.planned_start?.toISOString(),
      planned_end: values.planned_end?.toISOString(),
      equipment_id: values.equipment_id || undefined,
    })
    if (r.success) {
      message.success('已排程')
      setScheduleItem(null)
      onRefresh()
    } else {
      message.error(r.error)
    }
  }

  useEffect(() => {
    if (editItem) {
      editForm.setFieldsValue({
        intermediate_type_id: editItem.intermediate_type_id,
        intermediate_type_name: editItem.intermediate_type_name,
        route_id: editItem.route_id,
        equipment_id: editItem.equipment_id,
        planned_quantity: editItem.planned_quantity,
        unit: editItem.unit,
        priority: editItem.priority,
        remark: editItem.remark,
      })
    }
  }, [editItem, editForm])

  useEffect(() => {
    if (scheduleItem) {
      scheduleForm.setFieldsValue({
        planned_start: scheduleItem.planned_start ? dayjs(scheduleItem.planned_start) : undefined,
        planned_end: scheduleItem.planned_end ? dayjs(scheduleItem.planned_end) : undefined,
        equipment_id: scheduleItem.equipment_id || undefined,
      })
    }
  }, [scheduleItem, scheduleForm])

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const columns: ColumnsType<PlanItem> = [
    { title: '项号', dataIndex: 'item_no', key: 'item_no', width: 60 },
    { title: '产出物', dataIndex: 'intermediate_type_name', key: 'intermediate_type_name', width: 140 },
    {
      title: '计划数量',
      key: 'qty',
      width: 100,
      render: (_, r) => `${r.planned_quantity}${r.unit ? ` ${r.unit}` : ''}`,
    },
    { title: '设备', dataIndex: 'equipment_id', key: 'equipment_id', width: 100, render: v => v || '—' },
    {
      title: '计划时间',
      key: 'dates',
      width: 180,
      render: (_, r) => `${formatDate(r.planned_start)} ~ ${formatDate(r.planned_end)}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s: string) => {
        const c = ITEM_STATUS_CONFIG[s] ?? { label: s, color: 'default' }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 70,
      render: (p: string) => {
        const c = PRIORITY_CONFIG[p] ?? { label: p, color: 'default' }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, r) => {
        const canSchedule = r.status === 'draft' || r.status === 'scheduled'
        return (
          <Space size="small">
            {canEdit && (
              <>
                <Button size="small" type="link" onClick={() => openEditModal(r)}>编辑</Button>
                <Button size="small" type="link" danger onClick={() => handleDelete(r)}>删除</Button>
              </>
            )}
            {canSchedule && (
              <Button size="small" type="link" onClick={() => setScheduleItem(r)}>排程</Button>
            )}
          </Space>
        )
      },
    },
  ]

  if (isLoading) return <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>

  const handleIntermediateTypeSelect = (id: string, form: typeof addForm) => {
    const it = intermediateTypes.find((t: { id: string; name: string; default_unit: string | null }) => t.id === id)
    if (it) {
      form.setFieldsValue({ intermediate_type_name: it.name, unit: it.default_unit || 'kg' })
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>计划项</Text>
        {canEdit && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            添加计划项
          </Button>
        )}
      </div>

      {items.length === 0 ? (
        <Empty description="暂无计划项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table<PlanItem>
          dataSource={items}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 800 }}
        />
      )}

      {/* 添加 Modal */}
      <Modal
        title="添加计划项"
        open={addOpen}
        onOk={handleAdd}
        onCancel={() => { addForm.resetFields(); setAddOpen(false) }}
        destroyOnHidden
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="intermediate_type_id" label="产出物" rules={[{ required: true, message: '请选择产出物' }]}>
            <Select
              showSearch={{ onSearch: setIntermediateTypeKeyword, filterOption: false }}
              placeholder="搜索并选择产出物"
              onChange={(id) => handleIntermediateTypeSelect(id, addForm)}
              options={intermediateTypes.map((t: { id: string; name: string }) => ({
                value: t.id,
                label: t.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="intermediate_type_name" hidden><Input /></Form.Item>
          <Space size="middle" wrap>
            <Form.Item name="planned_quantity" label="计划数量" rules={[{ required: true }]}>
              <InputNumber min={0} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true }]}>
              <Input style={{ width: 80 }} />
            </Form.Item>
          </Space>
          <Space size="middle" wrap>
            <Form.Item name="route_id" label="工艺路线ID">
              <Input style={{ width: 280 }} />
            </Form.Item>
            <Form.Item name="equipment_id" label="设备ID">
              <Input style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select
              style={{ width: 100 }}
              options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 排程 Modal */}
      <Modal
        title={`排程 · ${scheduleItem?.intermediate_type_name ?? ''}`}
        open={!!scheduleItem}
        onOk={handleSchedule}
        onCancel={() => { scheduleForm.resetFields(); setScheduleItem(null) }}
        destroyOnHidden
      >
        <Form form={scheduleForm} layout="vertical">
          <Space size="middle" wrap>
            <Form.Item name="planned_start" label="计划开始时间" rules={[{ required: true, message: '请选择' }]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="planned_end" label="计划结束时间" rules={[{ required: true, message: '请选择' }]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: 200 }} />
            </Form.Item>
          </Space>
          <Form.Item name="equipment_id" label="设备ID">
            <Input style={{ width: 200 }} placeholder="输入设备编号或ID" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 Modal */}
      <Modal
        title="编辑计划项"
        open={!!editItem}
        onOk={handleEdit}
        onCancel={() => { editForm.resetFields(); setEditItem(null) }}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="intermediate_type_id" label="产出物" rules={[{ required: true, message: '请选择产出物' }]}>
            <Select
              showSearch={{ onSearch: setIntermediateTypeKeyword, filterOption: false }}
              placeholder="搜索并选择产出物"
              onChange={(id) => handleIntermediateTypeSelect(id, editForm)}
              options={intermediateTypes.map((t: { id: string; name: string }) => ({
                value: t.id,
                label: t.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="intermediate_type_name" hidden><Input /></Form.Item>
          <Space size="middle" wrap>
            <Form.Item name="planned_quantity" label="计划数量" rules={[{ required: true }]}>
              <InputNumber min={0} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true }]}>
              <Input style={{ width: 80 }} />
            </Form.Item>
          </Space>
          <Space size="middle" wrap>
            <Form.Item name="route_id" label="工艺路线ID">
              <Input style={{ width: 280 }} />
            </Form.Item>
            <Form.Item name="equipment_id" label="设备ID">
              <Input style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select
              style={{ width: 100 }}
              options={Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))}
            />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
