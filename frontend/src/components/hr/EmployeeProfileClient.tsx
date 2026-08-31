'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { App, Button, Tabs, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { fetchEmployeesAction, fetchDepartmentsAction, uploadEmployees, exportEmployees } from '@/actions/hr'
import { Employee, Department } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import { downloadBase64File } from '@/lib/hr'
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
  const [loading, setLoading] = useState(false)
  const seqRef = useRef(0)

  const { searchKeyword, filterStatus } = useHrStore()

  const activeDepartment =
    activeTab === 'all'
      ? ''
      : departments.find((d) => d.id === activeTab)?.name || ''

  const loadData = useCallback(async () => {
    const seq = ++seqRef.current
    setLoading(true)
    try {
      const res = await fetchEmployeesAction({
        keyword: searchKeyword || undefined,
        department: activeDepartment || undefined,
        status: filterStatus || undefined,
        page,
        page_size: pageSize,
        // 仅「全部」tab 按实际部门归属并入未分类；具体部门 tab 不混入未分类
        // （未分类人员有独立 tab）
        include_uncategorized: activeDepartment === '',
      })
      if (seq !== seqRef.current) return // 过期响应丢弃，防止旧页数据覆盖新页
      setEmployees(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      if (seq !== seqRef.current) return
      message.error(err.message || '加载数据失败')
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [searchKeyword, activeDepartment, filterStatus, page, pageSize])

  const loadDepartments = useCallback(async () => {
    try {
      const res = await fetchDepartmentsAction({ page_size: 100 })
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

  const handleExport = async () => {
    try {
      const r = await exportEmployees()
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
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

  // 搜索/状态/部门筛选变化时回到第一页，避免深页筛选后出现空页
  useEffect(() => {
    setPage((p) => (p === 1 ? p : 1))
  }, [searchKeyword, activeDepartment, filterStatus])

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
      // 未分类人员独立版面（不与有体现部门的人员混排）
      { key: 'uncategorized', label: '未分类', value: '未分类' },
    ],
    [departments]
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          员工档案
        </h1>
        <div className="flex gap-2">
          <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={async (file) => {
            const fd = new FormData(); fd.append('file', file as File)
            try {
              const d = await uploadEmployees(fd)
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
          <Button onClick={handleExport}>导出Excel</Button>
        </div>
      </div>


      <Tabs activeKey={activeTab} onChange={handleTabChange} type="card"
        items={tabItems.map((dept) => ({
          key: dept.key,
          label: dept.label,
          children: activeTab === dept.key ? (
            <EmployeeTable loading={loading}
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
