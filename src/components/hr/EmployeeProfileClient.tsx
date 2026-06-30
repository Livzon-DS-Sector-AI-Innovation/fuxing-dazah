'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import { App, Button, Select, Tabs, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { Employee, Department } from '@/types/hr'
import { fetchEmployeesAction } from '@/actions/hr'
import { fetchDepartments } from '@/lib/api/hr'
import { useHrStore } from '@/stores/hr'
import EmployeeTable from './EmployeeTable'
import EmployeeForm from './EmployeeForm'
import TurnoverAnalysisPanel from './TurnoverAnalysisPanel'

interface EmployeeProfileClientProps {
  initialEmployees: Employee[]
  initialTotal: number
  initialDepartment?: string
  fetchAction?: typeof fetchEmployeesAction
}

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debouncedValue
}

export default function EmployeeProfileClient({
  initialEmployees,
  initialTotal,
  initialDepartment,
  fetchAction }: EmployeeProfileClientProps) {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>(initialEmployees)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [activeTab, setActiveTab] = useState('all')
  const [departments, setDepartments] = useState<Department[]>([])

  const { searchKeyword, filterStatus } = useHrStore()
  const debouncedSearchKeyword = useDebounce(searchKeyword, 300)

  const activeDepartment =
    activeTab === 'all'
      ? ''
      : departments.find((d) => d.id === activeTab)?.name || ''

  const doFetch = fetchAction || fetchEmployeesAction

  const loadData = useCallback(async () => {
    try {
      const res = await doFetch({
        keyword: debouncedSearchKeyword || undefined,
        department: activeDepartment || undefined,
        status: filterStatus || undefined,
        page,
        page_size: pageSize })
      setEmployees(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    }
  }, [debouncedSearchKeyword, activeDepartment, filterStatus, page, pageSize, doFetch])

  const loadDepartments = useCallback(async () => {
    try {
      const res = await fetchDepartments({ page_size: 100 })
      setDepartments(res.data)
    } catch {
      setDepartments([])
    }
  }, [])

  // When initialDepartment is provided, select that department tab
  useEffect(() => {
    if (initialDepartment && departments.length > 0) {
      const dept = departments.find((d) => d.name === initialDepartment)
      if (dept) setActiveTab(dept.id)
    }
  }, [initialDepartment, departments])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleRefresh = () => {
    loadData()
    loadDepartments()
  }

  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee)
    setFormOpen(true)
  }

  const handleFormSuccess = () => {
    loadData()
  }

  const handleTabChange = (key: string) => {
    setActiveTab(key)
    setPage(1)
  }

  useEffect(() => {
    loadData()
  }, [debouncedSearchKeyword, activeDepartment, filterStatus, page, pageSize])

  useEffect(() => {
    loadDepartments()
  }, [loadDepartments])

  const tabItems = useMemo(
    () => [
      { key: 'all', label: '全部', value: '' },
      ...departments.map((d) => ({ key: d.id, label: d.name, value: d.name })),
    ],
    [departments]
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          员工档案
        </h1>
        <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({file}) => {
          const fd = new FormData(); fd.append('file', file as File)
          const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
          try {
            const res = await fetch(`${API_BASE}/api/v1/hr/employees/upload`, {method:'POST', body: fd, credentials: 'include'})
            const d = await res.json()
            if (res.ok) message.success(`上传完成：新增${d.data.created}，更新${d.data.updated}`)
            else message.error(d.message || '上传失败')
            handleRefresh()
          } catch { message.error('上传失败') }
        }}>
          <Button icon={<UploadOutlined />}>上传人员名单</Button>
        </Upload>
        <Select placeholder="选择部门下载花名册" allowClear style={{ width: 220 }}
          options={departments.map((d: any) => ({value: d.name, label: d.name}))}
          onChange={async (dept) => {
            if (!dept) return
            const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
            const deptEncoded = encodeURIComponent(dept)
            window.open(`${API_BASE}/api/v1/hr/roster?department=${deptEncoded}`)
          }} />
      </div>

      <TurnoverAnalysisPanel />

      <Tabs activeKey={activeTab} onChange={handleTabChange} type="card">
        {tabItems.map((dept) => (
          <Tabs.TabPane key={dept.key} tab={dept.label}>
            {activeTab === dept.key && (
              <EmployeeTable
                employees={employees}
                total={total}
                page={page}
                pageSize={pageSize}
                onPageChange={handlePageChange}
                onRefresh={handleRefresh}
                onEdit={handleEdit}
              />
            )}
          </Tabs.TabPane>
        ))}
      </Tabs>

      <EmployeeForm
        open={formOpen}
        employee={editingEmployee}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

    </div>
  )
}
