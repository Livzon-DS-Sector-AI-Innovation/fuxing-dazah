'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { App, Button, Table, Space, Popconfirm, Input, Modal, Tag, Descriptions } from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { Department, Employee } from '@/types/hr'
import { fetchDepartmentsAction, deleteDepartment } from '@/actions/hr'
import { fetchEmployees } from '@/lib/api/hr'
import DepartmentForm from './DepartmentForm'
import TeamClient from './TeamClient'

interface DepartmentClientProps {
  initialDepartments: Department[]
  initialTotal: number
  fetchAction?: typeof fetchDepartmentsAction
}

export default function DepartmentClient({
  initialDepartments,
  initialTotal,
  fetchAction }: DepartmentClientProps) {
  const { message } = App.useApp()
  const [departments, setDepartments] = useState<Department[]>(initialDepartments)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const router = useRouter()
  const [teamModalOpen, setTeamModalOpen] = useState(false)
  const [selectedDepartment, setSelectedDepartment] = useState<Department | null>(null)

  // 展开行：部门员工列表
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())
  const [employeesByDept, setEmployeesByDept] = useState<Record<string, Employee[]>>({})
  const [loadingEmployees, setLoadingEmployees] = useState<Set<string>>(new Set())
  const [detailEmployee, setDetailEmployee] = useState<Employee | null>(null)

  const doFetch = fetchAction || fetchDepartmentsAction

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await doFetch({
        keyword: searchKeyword || undefined,
        page,
        page_size: pageSize })
      setDepartments(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [searchKeyword, page, pageSize, doFetch])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleRefresh = () => {
    setExpandedKeys(new Set())
    setEmployeesByDept({})
    loadData()
  }

  const handleEdit = (department: Department) => {
    setEditingDepartment(department)
    setFormOpen(true)
  }

  const handleAdd = () => {
    setEditingDepartment(null)
    setFormOpen(true)
  }

  const handleFormSuccess = () => {
    loadData()
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteDepartment(id)
      message.success('删除成功')
      loadData()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleOpenTeams = (department: Department) => {
    setSelectedDepartment(department)
    setTeamModalOpen(true)
  }

  // 加载部门下的员工
  const loadEmployeesForDept = async (deptName: string) => {
    if (employeesByDept[deptName]) return // 已加载过

    setLoadingEmployees((prev) => new Set(prev).add(deptName))
    try {
      // 分页加载该部门全部员工
      let allEmployees: Employee[] = []
      let page = 1
      const pageSize = 200
      while (true) {
        const res = await fetchEmployees({ department: deptName, page, page_size: pageSize })
        const data = res.data || []
        allEmployees = allEmployees.concat(data)
        if (data.length < pageSize) break
        page++
      }
      setEmployeesByDept((prev) => ({ ...prev, [deptName]: allEmployees }))
    } catch {
      message.error(`加载 ${deptName} 人员失败`)
    } finally {
      setLoadingEmployees((prev) => {
        const next = new Set(prev)
        next.delete(deptName)
        return next
      })
    }
  }

  const handleExpand = (expanded: boolean, record: Department) => {
    const next = new Set(expandedKeys)
    if (expanded) {
      next.add(record.id)
      loadEmployeesForDept(record.name)
    } else {
      next.delete(record.id)
    }
    setExpandedKeys(next)
  }

  useEffect(() => {
    loadData()
  }, [searchKeyword, page, pageSize])

  const employeeColumns = [
    { title: '工号', dataIndex: 'employee_number', width: 110 },
    { title: '姓名', dataIndex: 'name', width: 100,
      render: (name: string, record: Employee) => (
        <a onClick={() => setDetailEmployee(record)}>{name}</a>
      )},
    { title: '职位', dataIndex: 'position', width: 140, ellipsis: true },
    { title: '职级', dataIndex: 'level', width: 80 },
    { title: '岗位类别', dataIndex: 'job_category', width: 80 },
    { title: '状态', dataIndex: 'status', width: 80,
      render: (s: string) => <Tag color={s === '在职' ? 'green' : s === '离职' ? 'red' : 'default'}>{s}</Tag> },
    { title: '入职日期', dataIndex: 'hire_date', width: 110 },
    { title: '手机', dataIndex: 'phone', width: 120, ellipsis: true },
    { title: '员工性质', dataIndex: 'status_category', width: 90 },
  ]

  const columns = [
    {
      title: '部门编码',
      dataIndex: 'code',
      key: 'code',
      width: 120 },
    {
      title: '部门名称',
      dataIndex: 'name',
      key: 'name',
      width: 180 },
    {
      title: '人数',
      dataIndex: 'employee_count',
      key: 'employee_count',
      width: 80,
      render: (count: number, record: Department) => (
        <a onClick={() => router.push(`/hr/profile?department=${encodeURIComponent(record.name)}`)}>
          {count || 0} 人
        </a>
      ) },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: any, record: Department) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<TeamOutlined />}
            onClick={() => handleOpenTeams(record)}
          >
            班组
          </Button>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description={`确定要删除部门 ${record.name} 吗？`}
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
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          部门管理
        </h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
          新增部门
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索部门名称或编码"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={departments}
        rowKey="id"
        loading={loading}
        expandable={{
          expandedRowKeys: Array.from(expandedKeys),
          onExpand: handleExpand,
          expandedRowRender: (record: Department) => {
            const employees = employeesByDept[record.name]
            const isLoading = loadingEmployees.has(record.name)
            return (
              <div className="py-2">
                <div className="text-sm text-gray-500 mb-2">
                  <UserOutlined className="mr-1" />
                  {record.name} — 共 {employees ? employees.length : record.employee_count || 0} 人
                </div>
                <Table
                  columns={employeeColumns}
                  dataSource={employees || []}
                  rowKey="id"
                  loading={isLoading}
                  size="small"
                  pagination={false}
                  scroll={{ x: 900 }}
                />
              </div>
            )
          },
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: handlePageChange }}
      />

      <DepartmentForm
        open={formOpen}
        department={editingDepartment}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

      <Modal
        open={teamModalOpen}
        onCancel={() => setTeamModalOpen(false)}
        footer={null}
        width={800}
      >
        {selectedDepartment && (
          <TeamClient
            departmentId={selectedDepartment.id}
            departmentName={selectedDepartment.name}
          />
        )}
      </Modal>

      <Modal title={`${detailEmployee?.name || ''} - 详细资料`} open={!!detailEmployee}
        onCancel={() => setDetailEmployee(null)} footer={null} width={700}>
        {detailEmployee && (
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="工号">{detailEmployee.employee_number}</Descriptions.Item>
            <Descriptions.Item label="姓名">{detailEmployee.name}</Descriptions.Item>
            <Descriptions.Item label="部门">{detailEmployee.department}</Descriptions.Item>
            <Descriptions.Item label="职务">{detailEmployee.duty}</Descriptions.Item>
            <Descriptions.Item label="岗位">{detailEmployee.position}</Descriptions.Item>
            <Descriptions.Item label="职级">{detailEmployee.level}</Descriptions.Item>
            <Descriptions.Item label="岗位类别">{detailEmployee.job_category}</Descriptions.Item>
            <Descriptions.Item label="性别">{detailEmployee.gender}</Descriptions.Item>
            <Descriptions.Item label="学历">{detailEmployee.education}</Descriptions.Item>
            <Descriptions.Item label="毕业院校">{detailEmployee.school}</Descriptions.Item>
            <Descriptions.Item label="专业">{detailEmployee.major}</Descriptions.Item>
            <Descriptions.Item label="入职日期">{detailEmployee.hire_date}</Descriptions.Item>
            <Descriptions.Item label="员工性质">{detailEmployee.status_category}</Descriptions.Item>
            <Descriptions.Item label="状态">{detailEmployee.status}</Descriptions.Item>
            <Descriptions.Item label="手机">{detailEmployee.phone}</Descriptions.Item>
            <Descriptions.Item label="域账号">{detailEmployee.domain_account}</Descriptions.Item>
            <Descriptions.Item label="部门管理者">{detailEmployee.dept_manager}</Descriptions.Item>
            <Descriptions.Item label="报表用职级">{detailEmployee.report_grade}</Descriptions.Item>
            <Descriptions.Item label="出生年月">{detailEmployee.birth_year}/{detailEmployee.birth_month}/{detailEmployee.birth_day}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

    </div>
  )
}
