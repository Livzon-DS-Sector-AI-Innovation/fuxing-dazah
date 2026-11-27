'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  App, Button, Checkbox, Table, Space, Popconfirm, Input, Modal, Tag, Descriptions, Tooltip,
} from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, UserOutlined } from '@ant-design/icons'
import { Department, Employee, type ManagerAccountStatus } from '@/types/hr'
import { fetchDepartmentsAction, fetchEmployeesAction, deleteDepartment } from '@/actions/hr'
import { EMPLOYEE_STATUS_TAG_COLORS } from '@/lib/hr'
import { useDebouncedCallback } from '@/hooks/hr'
import DepartmentForm from './DepartmentForm'
import PageHeader from './PageHeader'

/** 账号未就绪的三种原因：标签文案 + 给 HR 的处理说明 */
const MANAGER_ISSUE_META: Record<
  Exclude<ManagerAccountStatus, 'ok'>,
  { color: string; text: string; tip: string }
> = {
  no_account: {
    color: 'orange',
    text: '未登录过系统',
    tip: '系统按姓名匹配他的登录账号来发提醒和审批。此人还没登录过本系统，收不到；请他用飞书扫码登录一次。',
  },
  ambiguous: {
    color: 'red',
    text: '同名多账号',
    tip: '系统里有多个同名账号，无法确定发给谁，提醒和审批都不会发。请改为其他人，或联系管理员处理同名账号。',
  },
  left: {
    color: 'red',
    text: '已离职',
    tip: '此人已不在职，提醒和审批仍会继续发给他。请更换。',
  },
}

/** 负责人 / 分管领导单元格：姓名 + 未就绪原因标签（就绪的不加标记，避免满屏标签） */
function ManagerCell({ name, status }: { name?: string | null; status?: ManagerAccountStatus | '' | null }) {
  if (!name) return <span className="text-gray-400">-</span>
  const issue = status && status !== 'ok' ? MANAGER_ISSUE_META[status] : undefined
  return (
    <Space size={4} wrap>
      <span>{name}</span>
      {issue && (
        <Tooltip title={issue.tip}>
          <Tag color={issue.color} style={{ marginInlineEnd: 0 }}>{issue.text}</Tag>
        </Tooltip>
      )}
    </Space>
  )
}

/** 部门负责人需要处理：没填，或账号未就绪（分管领导只影响转正审批，不进这个筛选） */
function needsManagerAttention(d: Department): boolean {
  return !d.department_manager_name || d.manager_account_status !== 'ok'
}

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
  // 输入框即时回显值；防抖后才写入 searchKeyword 触发查询（此前每敲一个字发一次请求）
  const [keywordInput, setKeywordInput] = useState('')
  const loadSeq = useRef(0)
  const router = useRouter()

  const { run: debouncedSetKeyword, cancel: cancelKeywordDebounce } = useDebouncedCallback((val: string) => {
    setPage(1)
    setSearchKeyword(val)
  }, 300)

  const commitKeyword = (val: string) => {
    cancelKeywordDebounce()
    setPage(1)
    setSearchKeyword(val.trim())
  }

  // 展开行：部门员工列表
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())
  const [employeesByDept, setEmployeesByDept] = useState<Record<string, Employee[]>>({})
  const [loadingEmployees, setLoadingEmployees] = useState<Set<string>>(new Set())
  const [detailEmployee, setDetailEmployee] = useState<Employee | null>(null)

  const doFetch = fetchAction || fetchDepartmentsAction

  /** 拉当前页；请求序号守卫：慢响应回来时若已有更新的查询，返回 null 让调用方丢弃 */
  const fetchPage = useCallback(async () => {
    const seq = ++loadSeq.current
    const res = await doFetch({
      keyword: searchKeyword || undefined,
      page,
      page_size: pageSize })
    return seq === loadSeq.current ? res : null
  }, [searchKeyword, page, pageSize, doFetch])

  // 事件驱动的刷新（新增 / 编辑 / 删除后）：可以直接进 loading
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchPage()
      if (!res) return
      setDepartments(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [fetchPage, message])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
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
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败')
    }
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
        const res = await fetchEmployeesAction({ department: deptName, page, page_size: pageSize })
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

  // 筛选 / 翻页变化时重新加载：请求写在 effect 内部，setState 都在 await 之后
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetchPage()
        if (!cancelled && res) {
          setDepartments(res.data)
          setTotal(res.meta?.total || 0)
        }
      } catch (err) {
        if (!cancelled) message.error(err instanceof Error ? err.message : '加载数据失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchPage])

  // 「只看负责人需要处理的」：在当前页数据里筛选（部门总量不大，翻页时逐页看）
  const [onlyAttention, setOnlyAttention] = useState(false)
  const managerReady = departments.filter((d) => d.department_manager_name && d.manager_account_status === 'ok').length
  const managerUnset = departments.filter((d) => !d.department_manager_name).length
  const managerUnready = departments.length - managerReady - managerUnset
  const shownRows = onlyAttention ? departments.filter(needsManagerAttention) : departments

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
      render: (s: string) => <Tag color={EMPLOYEE_STATUS_TAG_COLORS[s] || 'default'}>{s}</Tag> },
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
      title: '部门负责人',
      dataIndex: 'department_manager_name',
      key: 'department_manager_name',
      width: 190,
      render: (v: string | null, record: Department) => (
        <ManagerCell name={v} status={record.manager_account_status} />
      ),
    },
    {
      title: '分管领导',
      dataIndex: 'supervising_leader_name',
      key: 'supervising_leader_name',
      width: 190,
      render: (v: string | null, record: Department) => (
        <ManagerCell name={v} status={record.leader_account_status} />
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: Department) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除部门"
            // 有员工的部门删除后在确认里写明人数，避免误以为人员会随之处理
            description={record.employee_count
              ? `「${record.name}」下现有 ${record.employee_count} 名员工，删除部门不会改动这些人员的档案。确定删除？`
              : `确定要删除部门 ${record.name} 吗？`}
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
            okButtonProps={{ danger: true }}
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
      <PageHeader
        title="部门管理"
        description="维护组织架构；部门负责人接收劳动合同到期续签审批提醒，与分管领导同为转正评估第二、三级审批人（均需登录过系统）。收不到提醒的会在姓名旁标出原因"
        actions={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新增部门
          </Button>
        }
      />

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索部门名称或编码"
          value={keywordInput}
          onChange={(e) => { setKeywordInput(e.target.value); debouncedSetKeyword(e.target.value.trim()) }}
          onPressEnter={(e) => commitKeyword((e.target as HTMLInputElement).value)}
          prefix={<SearchOutlined />}
          // antd 输入框自带 width:100%，Tailwind 的 w-64 会被覆盖成整行宽，宽度须走 style
          style={{ width: 260 }}
          allowClear
        />
        <Checkbox
          checked={onlyAttention}
          onChange={(e) => { setOnlyAttention(e.target.checked); if (e.target.checked) setPage(1) }}
        >
          只看负责人需要处理的（未填或账号未就绪）
        </Checkbox>
      </div>

      {departments.length > 0 && (
        <div className="text-[13px] text-gray-500">
          本页部门负责人：已就绪 {managerReady} · 未填 {managerUnset}
          {managerUnready > 0 && (
            <span className="text-orange-600"> · 账号未就绪 {managerUnready}（把鼠标放到标签上可看处理办法）</span>
          )}
        </div>
      )}

      <Table
        columns={columns}
        dataSource={shownRows}
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
          // 筛选只作用于当前页数据，分页总数仍是全部部门
          showTotal: (t) => (onlyAttention ? `共 ${t} 条（筛选仅作用于当前页）` : `共 ${t} 条`),
          onChange: handlePageChange }}
      />

      <DepartmentForm
        open={formOpen}
        department={editingDepartment}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

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
            <Descriptions.Item label="报表用职级">{detailEmployee.report_grade}</Descriptions.Item>
            <Descriptions.Item label="出生年月">{detailEmployee.birth_year}/{detailEmployee.birth_month}/{detailEmployee.birth_day}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

    </div>
  )
}
