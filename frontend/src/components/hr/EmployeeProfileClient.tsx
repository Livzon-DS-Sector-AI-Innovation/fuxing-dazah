'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import { App, Button, Tabs, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { fetchEmployees, fetchDepartments, API_BASE } from '@/lib/hr'
import { Employee, Department } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import EmployeeTable from './EmployeeTable'
import EmployeeForm from './EmployeeForm'

interface EmployeeProfileClientProps {
  initialEmployees: Employee[]
  initialTotal: number
  initialDepartment?: string
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
  initialDepartment }: EmployeeProfileClientProps) {
  const { message, modal } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>(initialEmployees)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [activeTab, setActiveTab] = useState('all')
  const [departments, setDepartments] = useState<Department[]>([])

  const { searchKeyword, filterStatus } = useHrStore()

  const activeDepartment =
    activeTab === 'all'
      ? ''
      : departments.find((d) => d.id === activeTab)?.name || ''

  const loadData = useCallback(async () => {
    try {
      const res = await fetchEmployees({
        keyword: searchKeyword || undefined,
        department: activeDepartment || undefined,
        status: filterStatus || undefined,
        page,
        page_size: pageSize })
      setEmployees(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    }
  }, [searchKeyword, activeDepartment, filterStatus, page, pageSize])

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
  }, [searchKeyword, activeDepartment, filterStatus, page, pageSize])

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
        <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={async (file) => {
          const fd = new FormData(); fd.append('file', file as File)
          try {
            const r = await fetch(`${API_BASE}/api/v1/hr/employees/upload`, { method: 'POST', body: fd, credentials: 'include' })
            const d = await r.json()
            if (!r.ok) {
              const errMsg = d.message || d.detail || `HTTP ${r.status}`
              throw new Error(errMsg)
            }
            const { created, updated, errors } = d.data
            if (errors && errors.length > 0) {
              modal.warning({
                title: `上传完成：新增${created}，更新${updated}，但有${errors.length}行出错`,
                content: <ul style={{maxHeight:300, overflow:'auto', paddingLeft:18}}>{errors.map((e:string,i:number)=><li key={i}>{e}</li>)}</ul>,
                width: 500,
              })
            } else {
              message.success(`上传完成：新增${created}，更新${updated}`)
            }
            handleRefresh()
          } catch (err: any) {
            message.error(err.message || '上传失败')
          }
          return false
        }}>
          <Button icon={<UploadOutlined />}>上传人员名单</Button>
        </Upload>
      </div>


      <Tabs activeKey={activeTab} onChange={handleTabChange} type="card"
        items={tabItems.map((dept) => ({
          key: dept.key,
          label: dept.label,
          children: activeTab === dept.key ? (
            <EmployeeTable
              employees={employees}
              total={total}
              page={page}
              pageSize={pageSize}
              onPageChange={handlePageChange}
              onRefresh={handleRefresh}
              onEdit={handleEdit}
            />
          ) : null,
        }))}
      />

      <EmployeeForm
        open={formOpen}
        employee={editingEmployee}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

    </div>
  )
}
