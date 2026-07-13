'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Table, Input, Select, Space, Tag, Upload, Modal, Form, DatePicker, Popconfirm } from 'antd'
import { SearchOutlined, UploadOutlined, EditOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export default function TrainersPage() {
  const { message } = App.useApp()
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [dept, setDept] = useState<string | undefined>()
  const [level1, setLevel1] = useState<string | undefined>()
  const [depts, setDepts] = useState<{value:string,label:string}[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`).then(r => r.json())
      .then(res => setDepts((res.data||[]).map((d:string) => ({value:d,label:d}))))
  }, [])

  const load = async (p = 1) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(p), page_size: '50' })
      if (keyword) params.set('keyword', keyword)
      if (dept) params.set('department', dept)
      if (level1) params.set('is_level1', level1)
      const res = await fetch(`${API_BASE}/api/v1/hr/trainers?${params.toString()}`)
      const d = await res.json()
      setData(d.data || [])
      setTotal(d.meta?.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { load(page) }, [page, dept, level1])

  const openEdit = (record?: any) => {
    if (record) {
      setEditing(record)
      form.setFieldsValue({
        ...record,
        trainable_departments: record.trainable_departments ? record.trainable_departments.split(',').map((s:string) => s.trim()) : [],
        certification_date: record.certification_date ? dayjs(record.certification_date) : null,
        confirmation_date: record.confirmation_date ? dayjs(record.confirmation_date) : null,
        confirmation_reminder: record.confirmation_reminder ? dayjs(record.confirmation_reminder) : null,
      })
    } else {
      setEditing(null)
      form.resetFields()
    }
    setModalOpen(true)
  }

  const handleSave = async () => {
    const vals = await form.validateFields()
    const payload = { ...vals }
    if (Array.isArray(payload.trainable_departments)) payload.trainable_departments = payload.trainable_departments.join(',')
    if (payload.certification_date) payload.certification_date = payload.certification_date.format('YYYY-MM-DD')
    if (payload.confirmation_date) payload.confirmation_date = payload.confirmation_date.format('YYYY-MM-DD')
    if (payload.confirmation_reminder) payload.confirmation_reminder = payload.confirmation_reminder.format('YYYY-MM-DD')

    const url = editing
      ? `${API_BASE}/api/v1/hr/trainers/${editing.id}`
      : `${API_BASE}/api/v1/hr/trainers`
    const method = editing ? 'PUT' : 'POST'
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    if (res.ok) {
      message.success(editing ? '已更新' : '已创建')
      setModalOpen(false)
      load(page)
    } else {
      const d = await res.json()
      message.error(d.message || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    const res = await fetch(`${API_BASE}/api/v1/hr/trainers/${id}`, { method: 'DELETE' })
    if (res.ok) { message.success('已删除'); load(page) }
    else message.error('删除失败')
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold">内训师台账</h1>
        <Space>
          <Button icon={<PlusOutlined />} onClick={() => openEdit()}>新增内训师</Button>
          <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({ file }) => {
            const fd = new FormData(); fd.append('file', file as File)
            try {
              const res = await fetch(`${API_BASE}/api/v1/hr/trainers/upload`, { method: 'POST', body: fd })
              const d = await res.json()
              if (res.ok) message.success(`上传完成：新增${d.data.created}，更新${d.data.updated}`)
              else message.error(d.message || '上传失败')
              load(1)
            } catch { message.error('上传失败') }
          }}>
            <Button icon={<UploadOutlined />}>上传内训师</Button>
          </Upload>
        </Space>
      </div>
      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input prefix={<SearchOutlined />} placeholder="搜索姓名" value={keyword}
            onChange={e => setKeyword(e.target.value)} onPressEnter={() => load(1)} style={{ width: 200 }} />
          <Select placeholder="部门" allowClear value={dept} onChange={v => { setDept(v); setPage(1) }}
            options={depts} style={{ width: 200 }} />
          <Select placeholder="一级培训师" allowClear value={level1} style={{ width: 140 }}
            onChange={v => { setLevel1(v); setPage(1) }}
            options={[{value:'一级培训师',label:'是'},{value:'-',label:'否'}]} />
        </Space>
        <Table dataSource={data} rowKey="id" loading={loading} scroll={{ x: 1400 }} size="small"
          pagination={{ current: page, pageSize: 50, total, onChange: p => setPage(p) }}
          columns={[
            { title: '可培训部门', dataIndex: 'trainable_departments', width: 200,
              render: (v: string) => v ? v.split(',').map((d: string) => <Tag key={d}>{d.trim()}</Tag>) : '-' },
            { title: '姓名', dataIndex: 'name', width: 80, fixed: 'left' as const },
            { title: '部门', dataIndex: 'department', width: 140 },
            { title: '资格范围', dataIndex: 'qualification_scope', width: 240, ellipsis: true },
            { title: '认证日期', dataIndex: 'certification_date', width: 110 },
            { title: '确认日期', dataIndex: 'confirmation_date', width: 110 },
            { title: '确认提醒', dataIndex: 'confirmation_reminder', width: 110 },
            { title: '备注', dataIndex: 'remarks', width: 120, ellipsis: true },
            { title: '一级培训师', dataIndex: 'is_level1', width: 100,
              render: (v: string) => v === '一级培训师' ? <Tag color="blue">是</Tag> : <Tag>-</Tag> },
            { title: '培训管理员', dataIndex: 'admin', width: 90 },
            { title: '操作', width: 100, fixed: 'right' as const,
              render: (_: any, record: any) => (
                <Space size="small">
                  <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
                  <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              )},
          ]} />
      </Card>

      <Modal title={editing ? '编辑内训师' : '新增内训师'} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={handleSave} okText="保存" width={600}>
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="department" label="部门" rules={[{ required: true }]}>
            <Select options={depts} showSearch /></Form.Item>
          <Form.Item name="trainable_departments" label="可培训部门">
            <Select mode="multiple" placeholder="选择可培训部门" options={depts} showSearch
              filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="qualification_scope" label="资格范围"><Input /></Form.Item>
          <Form.Item name="certification_date" label="认证日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="confirmation_date" label="确认日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="confirmation_reminder" label="确认提醒"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="is_level1" label="是否一级培训师">
            <Select options={[{value:'一级培训师',label:'一级培训师'},{value:'-',label:'否'}]} /></Form.Item>
          <Form.Item name="admin" label="培训管理员"><Input /></Form.Item>
          <Form.Item name="remarks" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
