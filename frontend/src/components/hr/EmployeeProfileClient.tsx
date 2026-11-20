'use client'

// 员工档案页容器：页头 + 部门页签 + 工具栏 + 筛选面板 + 员工表格。
// 数据加载已收敛至 hooks/hr（列表/部门/筛选选项），本组件只保留查询条件编排与一次性动作（导出/同步）。

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { App, Button, Tabs } from 'antd'
import { DownloadOutlined, SyncOutlined } from '@ant-design/icons'
import { exportEmployees, triggerEmployeeSync } from '@/actions/hr'
import { Employee, EmployeeSyncBanner, EmployeeFieldFilters } from '@/types/hr'
import { useHrStore } from '@/stores/hr'
import { downloadBase64File, fieldFiltersToParams } from '@/lib/hr'
import { useDebouncedCallback } from '@/hooks/useDebounce'
import { useEmployeeList, useHrDepartments, useHrFilterOptions } from '@/hooks/hr'
import PageHeader from './PageHeader'
import EmployeeTable from './EmployeeTable'
import EmployeeForm from './EmployeeForm'
import EmployeeFilterPanel, { countActiveFilters } from './EmployeeFilterPanel'
import ProfileToolbar from './employee/ProfileToolbar'

interface EmployeeProfileClientProps {
  /** 下钻进入时预选的部门名（编制页等部门跳转） */
  initialDepartment?: string
  /** 多维表格同步启用时传入：页面转只读展示 */
  syncInfo?: EmployeeSyncBanner
  /** 标题行右侧的动作区（页面级入口按钮，如信息收集/转正管理面板） */
  headerActions?: ReactNode
}

export default function EmployeeProfileClient({
  initialDepartment,
  syncInfo,
  headerActions }: EmployeeProfileClientProps) {
  const { message } = App.useApp()
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [activeTab, setActiveTab] = useState('all')
  const [filters, setFilters] = useState<EmployeeFieldFilters>({})
  const [filterOpen, setFilterOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const { searchKeyword, setSearchKeyword, filterStatus, setFilterStatus } = useHrStore()
  // 防抖搜索：停止输入 300ms 才写入 keyword 触发查询，避免逐键请求乱序
  const { run: debouncedSetKeyword, cancel: cancelKeywordDebounce } = useDebouncedCallback(
    (val: string) => setSearchKeyword(val),
    300,
  )

  const { departments, refresh: refreshDepartments } = useHrDepartments()
  const { filterOptions, refresh: refreshFilterOptions } = useHrFilterOptions()

  const activeDepartment =
    activeTab === 'all'
      ? ''
      : departments.find((d) => d.id === activeTab)?.name || ''

  const {
    employees, total, page, pageSize, loading, onPaginationChange, refresh: refreshList,
  } = useEmployeeList({
    keyword: searchKeyword,
    department: activeDepartment,
    status: filterStatus,
    // 仅「全部」tab 按实际部门归属并入未分类；具体部门 tab 不混入未分类
    // （未分类人员有独立 tab）
    includeUncategorized: activeDepartment === '',
    filters,
  })

  const activeFilterCount = useMemo(() => countActiveFilters(filters), [filters])

  // ?department=xxx：编制页等部门下钻进入时预选部门页签
  useEffect(() => {
    if (initialDepartment && departments.length > 0) {
      const dept = departments.find((d) => d.name === initialDepartment)
      if (dept) setActiveTab(dept.id)
    }
  }, [initialDepartment, departments])

  const handleRefresh = () => {
    refreshList()
    refreshDepartments()
    refreshFilterOptions()
  }

  const handleExport = async () => {
    try {
      // 与列表查询同口径传参，导出内容=当前筛选结果，避免"以为导的是筛选结果"
      const r = await exportEmployees({
        keyword: searchKeyword || undefined,
        department: activeDepartment || undefined,
        status: filterStatus || undefined,
        include_uncategorized: activeDepartment === '',
        ...fieldFiltersToParams(filters),
      })
      downloadBase64File(r.base64, r.filename)
      message.success(`已按当前筛选导出 ${total} 条`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    }
  }

  const handleSyncNow = async () => {
    setSyncing(true)
    try {
      const d = await triggerEmployeeSync()
      const s = d.data || {}
      message.success(
        `同步完成：新增 ${s.created ?? 0}，更新 ${s.updated ?? 0}，删除 ${s.deleted ?? 0}，共 ${s.total ?? 0} 条`,
        6,
      )
      handleRefresh()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee)
    setFormOpen(true)
  }

  const handleFormSuccess = () => {
    refreshList()
  }

  const handleTabChange = (key: string) => {
    setActiveTab(key)
  }

  const handleKeywordCommit = (val: string) => {
    cancelKeywordDebounce()
    setSearchKeyword(val)
  }

  const tabItems = useMemo(
    () => [
      { key: 'all', label: '全部' },
      ...departments.map((d) => ({ key: d.id, label: d.name })),
      // 未分类人员独立版面（不与有体现部门的人员混排）
      { key: 'uncategorized', label: '未分类' },
    ],
    [departments]
  )

  const lastSyncText = syncInfo?.last_sync_at ? syncInfo.last_sync_at.replace('T', ' ') : '从未'

  return (
    <div className="space-y-4">
      {/* 页头：标题 + 数据源副标题 ｜ 右侧动作区收拢所有入口 */}
      <PageHeader
        title="员工档案"
        description={
          syncInfo
            ? `数据来源：飞书多维表格（单向同步）· 只读展示 · 每天 02:00 自动同步 · 上次同步：${lastSyncText}`
            : undefined
        }
        actions={
          <>
            {headerActions}
            {syncInfo && (
              <Button icon={<SyncOutlined />} loading={syncing} onClick={handleSyncNow}>
                立即同步
              </Button>
            )}
            <Button icon={<DownloadOutlined />} onClick={handleExport}>
              导出Excel
            </Button>
          </>
        }
      />

      {/* 部门页签 + 右侧工具栏（搜索/状态/筛选）同行收纳；筛选面板展开在页签之下 */}
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        styles={{ header: { marginBottom: 8 } }}
        tabBarExtraContent={{
          right: (
            <ProfileToolbar
              keyword={searchKeyword}
              onKeywordInput={debouncedSetKeyword}
              onKeywordCommit={handleKeywordCommit}
              status={filterStatus}
              onStatusChange={(value) => setFilterStatus(value || '')}
              filterCount={activeFilterCount}
              onToggleFilter={() => setFilterOpen((v) => !v)}
            />
          ),
        }}
        items={tabItems.map((dept) => ({
          key: dept.key,
          label: dept.label,
          children: activeTab === dept.key ? (
            <>
              {filterOpen && (
                <EmployeeFilterPanel
                  options={filterOptions}
                  value={filters}
                  onChange={setFilters}
                  onClose={() => setFilterOpen(false)}
                />
              )}
              <EmployeeTable loading={loading}
                employees={employees}
                total={total}
                page={page}
                pageSize={pageSize}
                onPageChange={onPaginationChange}
                onEdit={handleEdit}
                syncMode={Boolean(syncInfo)}
              />
            </>
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
