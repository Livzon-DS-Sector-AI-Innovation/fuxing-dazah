'use client'

import { useState } from 'react'
import { App, Table, Button, Space, Tag, Input, Select, Popconfirm, Tooltip } from 'antd'
import { SearchOutlined, EditOutlined, DeleteOutlined, SyncOutlined, CheckCircleFilled } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import { deleteEmployee, syncToFeishuAction } from '@/actions/hr'

interface EmployeeTableProps {
  employees: Employee[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  onEdit: (employee: Employee) => void
}

const statusColorMap: Record<string, string> = {
  在职: 'success',
  试用期: 'warning',
  离职: 'default',
  待审批: 'processing' }

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  onEdit }: EmployeeTableProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [syncingId, setSyncingId] = useState<string | null>(null)
  const { searchKeyword, setSearchKeyword, filterStatus, setFilterStatus } = useHrStore()

  const handleDelete = async (id: string) => {
    setLoading(true)
    try {
      await deleteEmployee(id)
      message.success('删除成功')
      onRefresh()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSyncToFeishu = async (id: string) => {
    setSyncingId(id)
    try {
      const res = await syncToFeishuAction(id)
      message.success(`已同步到飞书: ${res.data.feishu_record_id}`)
      onRefresh()
    } catch (err: any) {
      message.error(err.message || '同步到飞书失败')
    } finally {
      setSyncingId(null)
    }
  }

  const columns = [
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      width: 110,
      fixed: 'left' as const },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 90,
      fixed: 'left' as const },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120 },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      width: 120 },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 70 },
    {
      title: '年龄',
      dataIndex: 'age',
      key: 'age',
      width: 70 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>{status}</Tag>
      ) },
    {
      title: '入职日期',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 110 },
    {
      title: '进厂时间',
      dataIndex: 'factory_entry_date',
      key: 'factory_entry_date',
      width: 110 },
    {
      title: '籍贯',
      dataIndex: 'native_place',
      key: 'native_place',
      width: 100 },
    {
      title: '政治面貌',
      dataIndex: 'political_status',
      key: 'political_status',
      width: 100 },
    {
      title: '婚姻状况',
      dataIndex: 'marital_status',
      key: 'marital_status',
      width: 100 },
    {
      title: '合同期限',
      dataIndex: 'contract_type',
      key: 'contract_type',
      width: 110 },
    {
      title: '职称类型',
      dataIndex: 'qualification_type',
      key: 'qualification_type',
      width: 100 },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 80 },
    {
      title: '司龄',
      dataIndex: 'company_tenure',
      key: 'company_tenure',
      width: 90 },
    {
      title: '毕业学校',
      dataIndex: 'school',
      key: 'school',
      width: 150 },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120 },
    {
      title: '飞书同步',
      key: 'feishu_sync',
      width: 100,
      fixed: 'right' as const,
      render: (_: any, record: Employee) => (
        record.feishu_record_id ? (
          <Tooltip title={`record_id: ${record.feishu_record_id}`}>
            <Tag color="success" icon={<CheckCircleFilled />}>已同步</Tag>
          </Tooltip>
        ) : (
          <Tag color="warning">未同步</Tag>
        )
      ) },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: any, record: Employee) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
          >
            编辑
          </Button>
          <Button
            type="text"
            size="small"
            icon={<SyncOutlined spin={syncingId === record.id} />}
            onClick={() => handleSyncToFeishu(record.id)}
            loading={syncingId === record.id}
          >
            同步
          </Button>
          <Popconfirm
            title="确认删除"
            description={`确定要删除员工 ${record.name} 吗？`}
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索姓名或工号"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
        <Select
          placeholder="状态筛选"
          value={filterStatus || undefined}
          onChange={(value) => setFilterStatus(value || '')}
          allowClear
          className="w-32"
          options={[
            { value: '在职', label: '在职' },
            { value: '试用期', label: '试用期' },
            { value: '离职', label: '离职' },
            { value: '待审批', label: '待审批' },
          ]}
        />
      </div>

      <Table
        columns={columns}
        dataSource={employees}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: onPageChange }}
        scroll={{ x: 2200 }}
        size="small"
      />
    </div>
  )
}
