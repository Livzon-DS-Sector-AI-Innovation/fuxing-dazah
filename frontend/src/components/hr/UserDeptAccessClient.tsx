'use client'

import { useEffect, useState, useCallback } from 'react'
import { App, Button, Card, Form, Select, Table, Popconfirm, Typography } from 'antd'
import { PlusOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { fetchUserDeptAccess, createUserDeptAccess, deleteUserDeptAccess, fetchTrainingAdmins, fetchHrDepartments } from '@/actions/hr'

const { Title } = Typography

interface UserDeptAccessRecord {
  id: string
  user_id: string
  user_name: string
  department: string
  created_at: string | null
}

interface TrainingAdmin {
  id: string
  name: string
  employee_no: string | null
}

export default function UserDeptAccessClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [records, setRecords] = useState<UserDeptAccessRecord[]>([])
  const [depts, setDepts] = useState<string[]>([])
  const [admins, setAdmins] = useState<TrainingAdmin[]>([])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [res, deptRes, adminRes] = await Promise.all([
        fetchUserDeptAccess({ page_size: 200 }),
        fetchHrDepartments(),
        fetchTrainingAdmins(),
      ])
      setRecords((res.data || []) as UserDeptAccessRecord[])
      const deptList: string[] = (deptRes?.data || []).map((d: any) => d.name || d)
      setDepts(deptList)
      setAdmins((adminRes?.data || []) as TrainingAdmin[])
    } catch (err: any) {
      message.error('加载数据失败: ' + (err.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { loadData() }, [loadData])

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      await createUserDeptAccess({ user_id: values.user_id, department: values.department })
      message.success('授权已添加')
      form.resetFields()
      loadData()
    } catch (err: any) {
      if (err?.message) message.error(err.message)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteUserDeptAccess(id)
      message.success('授权已移除')
      loadData()
    } catch (err: any) {
      message.error(err.message || '移除失败')
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'user_name', key: 'user_name', width: 150 },
    { title: '可访问部门', dataIndex: 'department', key: 'department', width: 200 },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180,
      render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, record: UserDeptAccessRecord) => (
        <Popconfirm title="确认移除该授权？" onConfirm={() => handleDelete(record.id)}>
          <Button danger size="small" icon={<DeleteOutlined />}>移除</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Card
      title={<Title level={5} style={{ margin: 0 }}>用户部门访问权限</Title>}
      extra={
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          刷新
        </Button>
      }
    >
      <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
        <Form.Item
          name="user_id"
          rules={[{ required: true, message: '请选择培训管理员' }]}
        >
          <Select
            showSearch
            placeholder="选择培训管理员"
            optionFilterProp="label"
            style={{ width: 240 }}
            options={admins.map(a => ({
                value: a.id,
                label: `${a.name}${a.employee_no ? ` (${a.employee_no})` : ''}`,
              }))}
          />
        </Form.Item>
        <Form.Item
          name="department"
          rules={[{ required: true, message: '请选择部门' }]}
        >
          <Select
            showSearch
            placeholder="选择部门"
            optionFilterProp="label"
            style={{ width: 200 }}
            options={depts.map(d => ({ value: d, label: d }))}
          />
        </Form.Item>
        <Form.Item>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            添加授权
          </Button>
        </Form.Item>
      </Form>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={records}
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        size="small"
      />
    </Card>
  )
}
