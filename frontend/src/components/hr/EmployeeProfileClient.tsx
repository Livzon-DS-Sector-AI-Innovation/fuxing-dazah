'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { App, Alert, Button, Tabs } from 'antd'
import { LinkOutlined, SyncOutlined } from '@ant-design/icons'
import { fetchEmployeesAction, fetchDepartmentsAction, exportEmployees, triggerEmployeeSync } from '@/actions/hr'
import { Employee, Department, EmployeeSyncBanner } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import { downloadBase64File } from '@/lib/hr'
import EmployeeTable from './EmployeeTable'
import EmployeeForm from './EmployeeForm'

interface EmployeeProfileClientProps {
  initialEmployees: Employee[]
  initialTotal: number
  initialDepartment?: string
  /** 多维表格同步启用时传入：页面转只读展示 */
  syncInfo?: EmployeeSyncBanner
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
  syncInfo }: EmployeeProfileClientProps) {
  const { message } = App.useApp()
  const [employees, setEmployees] = useState<Employee[]>(initialEmployees)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [activeTab, setActiveTab] = useState('all')
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
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

  const handleSyncNow = async () => {
    setSyncing(true)
    try {
      const d = await triggerEmployeeSync()
      const s = d.data || {}
      message.success(
        `同步完成：新增 ${s.created ?? 0}，更新 ${s.updated ?? 0}，删除 ${s.deleted ?? 0}`,
      )
      handleRefresh()
    } catch (err: any) {
      message.error(err.message || '同步失败')
    } finally {
      setSyncing(false)
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

  const bitableUrl = syncInfo?.app_token
    ? `https://feishu.cn/base/${syncInfo.app_token}${syncInfo.source_table_id ? `?table=${syncInfo.source_table_id}` : ''}`
    : null

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          员工档案
        </h1>
        <div className="flex gap-2">
          {syncInfo && (
            <>
              <Button icon={<SyncOutlined />} loading={syncing} onClick={handleSyncNow}>
                立即同步
              </Button>
              {bitableUrl && (
                <Button icon={<LinkOutlined />} href={bitableUrl} target="_blank">
                  在飞书打开
                </Button>
              )}
            </>
          )}
          <Button onClick={handleExport}>导出Excel</Button>
        </div>
      </div>

      {syncInfo && (
        <Alert
          type="info"
          showIcon
          message="数据来源：飞书多维表格（单向同步）"
          description={`档案在飞书多维表格中维护，此处为只读展示（实时同步 + 每 5 分钟对账）；上次同步：${syncInfo.last_sync_at ? syncInfo.last_sync_at.replace('T', ' ') : '从未'}。`}
        />
      )}

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
              syncMode={Boolean(syncInfo)}
            />
          ) : null,
        }))}
      />

      {!syncInfo && (
        <EmployeeForm
          open={formOpen}
          employee={editingEmployee}
          onClose={() => setFormOpen(false)}
          onSuccess={handleFormSuccess}
        />
      )}

    </div>
  )
}
