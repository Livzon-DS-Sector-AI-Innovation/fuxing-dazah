'use client'

import { useState } from 'react'
import { App, Table, Button, Space, Tag, Input, Select, Popconfirm, Modal } from 'antd'
import { SearchOutlined, EditOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons'
import { Employee } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import { deleteEmployee } from '@/actions/hr'

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
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEmp, setDetailEmp] = useState<Employee | null>(null)
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

  const allColumns: any[] = [
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
      width: 180 },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '兼任部门',
      dataIndex: 'concurrent_departments',
      key: 'concurrent_departments',
      width: 130,
      render: (v: string) => v || '-' },
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
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: any, record: Employee) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => { setDetailEmp(record); setDetailOpen(true) }}
          >
            详情
          </Button>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
          >
            编辑
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

  // Hide columns where ALL rows have empty values (except key & important columns)
  const alwaysShow = new Set(['action', 'employee_number', 'name', 'department', 'position', 'concurrent_departments'])
  const columns = allColumns.filter(col => {
    if (alwaysShow.has(col.key as string)) return true
    return employees.some((emp: any) => {
      const v = emp[col.dataIndex as string]
      return v !== null && v !== undefined && v !== ''
    })
  })

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

      <Modal title="员工详情" open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={600}>
        {detailEmp && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {[
                ['工号', detailEmp.employee_number], ['姓名', detailEmp.name],
                ['性别', detailEmp.gender], ['部门', detailEmp.department],
                ['岗位', detailEmp.position], ['学历', detailEmp.education],
                ['毕业院校', detailEmp.school], ['专业', detailEmp.major],
                ['毕业时间', detailEmp.graduation_date], ['入职日期', detailEmp.hire_date],
                ['职类', detailEmp.job_category], ['级别', detailEmp.level],
                ['域账号', detailEmp.domain_account], ['状态', detailEmp.status],
                ['手机', detailEmp.phone], ['邮箱', detailEmp.email],
                ['身份证号', detailEmp.id_card], ['籍贯', detailEmp.native_place],
                ['政治面貌', detailEmp.political_status], ['婚姻状况', detailEmp.marital_status],
              ].map(([label, val], i) => (
                <tr key={i}>
                  <td style={{ padding: '6px 12px', border: '1px solid #eee', background: '#f5f5f5', fontWeight: 600, width: '30%' }}>{label}</td>
                  <td style={{ padding: '6px 12px', border: '1px solid #eee' }}>{val || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>

    </div>
  )
}
