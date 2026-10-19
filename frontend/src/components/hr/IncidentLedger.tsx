'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { IncidentRecord } from '@/types/hr'
import { fetchIncidents, createIncident, updateIncident, deleteIncident } from '@/actions/hr'

const TYPE_META: Record<string, { label: string; color: string }> = {
  work_injury: { label: '工伤', color: 'red' },
  labor_dispute: { label: '劳动纠纷', color: 'orange' },
}

export default function IncidentLedger() {
  const { message } = App.useApp()
  const [data, setData] = useState<IncidentRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<IncidentRecord | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchIncidents(typeFilter, undefined)
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取台账失败')
    } finally {
      setLoading(false)
    }
  }, [message, typeFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (item: IncidentRecord) => {
    setEditing(item)
    form.setFieldsValue({
      incident_type: item.incident_type,
      employee_name: item.employee_name ?? undefined,
      employee_number: item.employee_number ?? undefined,
      department: item.department ?? undefined,
      occurred_date: item.occurred_date ? dayjs(item.occurred_date) : undefined,
      description: item.description ?? undefined,
      status: item.status,
      remark: item.remark ?? undefined,
    })
    setEditOpen(true)
  }

  const onSave = async () => {
    const values = await form.validateFields()
    const payload = {
      ...values,
      occurred_date: values.occurred_date ? values.occurred_date.format('YYYY-MM-DD') : undefined,
    }
    setSaving(true)
    try {
      if (editing) {
        await updateIncident(editing.id, payload)
        message.success('记录已更新')
      } else {
        await createIncident(payload)
        message.success('记录已新增')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onDelete = async (item: IncidentRecord) => {
    try {
      await deleteIncident(item.id)
      message.success('已删除')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          placeholder="类型筛选" allowClear style={{ width: 140 }}
          value={typeFilter}
          onChange={setTypeFilter}
          options={Object.entries(TYPE_META).map(([v, m]) => ({ value: v, label: m.label }))}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增记录</Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        scroll={{ x: 900 }}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: '类型', dataIndex: 'incident_type', width: 100,
            render: (v: string) => <Tag color={TYPE_META[v]?.color}>{TYPE_META[v]?.label ?? v}</Tag>,
          },
          { title: '当事人', dataIndex: 'employee_name', width: 110, render: (v: string | null) => v || '-' },
          { title: '部门', dataIndex: 'department', width: 130, render: (v: string | null) => v || '-' },
          { title: '发生日期', dataIndex: 'occurred_date', width: 110, render: (v: string | null) => v || '-' },
          { title: '情况描述', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v || '-' },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v: string) => v === 'closed' ? <Tag color="success">已结案</Tag> : <Tag color="processing">处理中</Tag>,
          },
          {
            title: '操作', key: 'actions', width: 120,
            render: (_: unknown, item: IncidentRecord) => (
              <Space size="small">
                <Button size="small" type="link" onClick={() => openEdit(item)}>编辑</Button>
                <Popconfirm title="确认删除该记录？" onConfirm={() => onDelete(item)}>
                  <Button size="small" type="link" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑记录' : '新增工伤/劳动纠纷记录'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        confirmLoading={saving}
        okText="保存"
        width={480}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="incident_type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select options={Object.entries(TYPE_META).map(([v, m]) => ({ value: v, label: m.label }))} />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="employee_name" label="当事人姓名" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="employee_number" label="工号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
          </Space>
          <Form.Item name="department" label="部门">
            <Input />
          </Form.Item>
          <Form.Item name="occurred_date" label="发生日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="情况描述">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="processing">
            <Select options={[{ value: 'processing', label: '处理中' }, { value: 'closed', label: '已结案' }]} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
