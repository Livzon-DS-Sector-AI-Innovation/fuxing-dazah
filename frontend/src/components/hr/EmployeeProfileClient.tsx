'use client'

// 员工档案页容器：页头 + 工具栏（部门下拉 / 搜索 / 状态 / 筛选 / 列设置）+ 筛选面板 + 员工表格。
// 数据加载已收敛至 hooks/hr（列表/部门/筛选选项），本组件只保留查询条件编排与一次性动作（导出/同步）。

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { App, Button, Select } from 'antd'
import { DownloadOutlined, SyncOutlined } from '@ant-design/icons'
import { exportEmployees, triggerEmployeeSync } from '@/actions/hr'
import { Employee, EmployeeSyncBanner, EmployeeFieldFilters } from '@/types/hr'
import { downloadBase64File, fieldFiltersToParams } from '@/lib/hr'
import { useDebouncedCallback, useEmployeeList, useHrDepartments, useHrFilterOptions } from '@/hooks/hr'
import PageHeader from './PageHeader'
import EmployeeTable from './EmployeeTable'
import EmployeeForm from './EmployeeForm'
import EmployeeFilterPanel, { countActiveFilters } from './EmployeeFilterPanel'
import ProfileToolbar from './employee/ProfileToolbar'
import ColumnSettings, { useProfileColumnSettings } from './employee/ColumnSettings'

interface EmployeeProfileClientProps {
  /** 多维表格同步启用时传入：页面转只读展示 */
  syncInfo?: EmployeeSyncBanner
  /** 标题行右侧的动作区（页面级入口按钮，如信息收集/转正管理面板） */
  headerActions?: ReactNode
}

/** 合成范围「未归类」在网址里的写法（部门为空或不在部门表中的员工；不是真实部门——部门表里那个叫「未分类」） */
const UNCATALOGED_PARAM = '未归类'

export default function EmployeeProfileClient({
  syncInfo,
  headerActions,
}: EmployeeProfileClientProps) {
  const { message } = App.useApp()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const urlDept = searchParams.get('department') ?? ''
  const urlStatus = searchParams.get('status') ?? ''
  const urlKeyword = searchParams.get('keyword') ?? ''

  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [filters, setFilters] = useState<EmployeeFieldFilters>({})
  const [filterOpen, setFilterOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  // 列设置：默认「常用列」，选择持久化在本地（employee/ColumnSettings）
  const columnSettings = useProfileColumnSettings()

  // ── 列表状态 = 网址的镜像 ──
  // 部门范围 / 状态 / 关键词都直接从网址初始化：从完整档案页返回、编制页下钻、别人发来的带筛选链接都能回到原视图。
  // （此前它们只在内存里，页面一跳走就丢；?status=试用期 这样的链接也不生效。）
  // 部门范围存「部门名」而不是 id：这样初始化时不必等部门表加载完成。
  const [activeDept, setActiveDept] = useState<string>(urlDept) // '' = 全公司
  const [status, setStatus] = useState<string>(urlStatus)
  const [keyword, setKeyword] = useState<string>(urlKeyword)

  // 防抖搜索：停止输入 300ms 才写入 keyword 触发查询，避免逐键请求乱序
  const { run: debouncedSetKeyword, cancel: cancelKeywordDebounce } = useDebouncedCallback(
    (val: string) => setKeyword(val),
    300,
  )

  const { departments, refresh: refreshDepartments } = useHrDepartments()
  const { filterOptions, refresh: refreshFilterOptions } = useHrFilterOptions()

  // 「未归类」：部门为空或不在部门表中的人员。它不是部门，activeDepartment 为空，
  // 靠 uncategorizedOnly 走后端专用过滤
  const isUncategorized = activeDept === UNCATALOGED_PARAM
  const activeDepartment = isUncategorized ? '' : activeDept

  const {
    employees, total, page, pageSize, loading, onPaginationChange, refresh: refreshList,
  } = useEmployeeList({
    keyword,
    department: activeDepartment,
    status,
    uncategorizedOnly: isUncategorized,
    filters,
  })

  const activeFilterCount = useMemo(() => countActiveFilters(filters), [filters])

  // 网址被外部改变（点侧边栏的裸链接、浏览器前进后退）时以网址为准恢复筛选。
  // 用「渲染期回同步」而不是 effect；页面自己 router.replace 写入的网址与当前状态必然一致，
  // 不回灌（否则打字过程中旧的网址晚到一步，会把关键词弹回旧值造成吃字）。
  const urlSig = `${urlDept}\u0000${urlStatus}\u0000${urlKeyword}`
  const stateSig = `${activeDept}\u0000${status}\u0000${keyword.trim()}`
  const [prevUrlSig, setPrevUrlSig] = useState(urlSig)
  if (urlSig !== prevUrlSig) {
    setPrevUrlSig(urlSig)
    if (urlSig !== stateSig) {
      setActiveDept(urlDept)
      setStatus(urlStatus)
      setKeyword(urlKeyword)
    }
  }

  // 筛选变化后把 部门 / 状态 / 关键词 镜像到网址（replace，不新增历史；关键词已防抖）
  useEffect(() => {
    const next = new URLSearchParams()
    if (isUncategorized) next.set('department', UNCATALOGED_PARAM)
    else if (activeDepartment) next.set('department', activeDepartment)
    if (status) next.set('status', status)
    const kw = keyword.trim()
    if (kw) next.set('keyword', kw)
    const target = next.toString()
    if (searchParams.toString() !== target) {
      router.replace(target ? `${pathname}?${target}` : pathname, { scroll: false })
    }
  }, [activeDepartment, isUncategorized, status, keyword, pathname, searchParams, router])

  const handleRefresh = () => {
    refreshList()
    refreshDepartments()
    refreshFilterOptions()
  }

  const handleExport = async () => {
    try {
      // 与列表查询同口径传参，导出内容=当前筛选结果，避免"以为导的是筛选结果"
      const r = await exportEmployees({
        keyword: keyword.trim() || undefined,
        department: activeDepartment || undefined,
        status: status || undefined,
        uncategorized_only: isUncategorized || undefined,
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

  const handleKeywordCommit = (val: string) => {
    cancelKeywordDebounce()
    setKeyword(val.trim())
  }

  // 部门下拉：此前是 39 个部门页签，1366 宽度下只露出 6 个，其余挤在「…」里
  const deptOptions = useMemo(
    () => [
      { value: '', label: '全公司' },
      ...departments.map((d) => ({ value: d.name, label: d.name })),
      { value: UNCATALOGED_PARAM, label: '未归类' },
    ],
    [departments],
  )

  const lastSyncText = syncInfo?.last_sync_at ? syncInfo.last_sync_at.replace('T', ' ') : '从未'

  return (
    <div className="space-y-4">
      {/* 页头：标题 + 数据源副标题 ｜ 右侧动作区收拢所有入口 */}
      <PageHeader
        title="员工档案"
        description={
          syncInfo
            ? `数据来源：飞书多维表格（单向同步）· 只读展示 · 每小时自动同步 · 上次同步：${lastSyncText}`
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

      {/* 工具栏一行：部门范围 ｜ 搜索 / 状态 / 筛选 ｜ 列设置 */}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          showSearch
          optionFilterProp="label"
          value={activeDept}
          onChange={setActiveDept}
          options={deptOptions}
          style={{ width: 200 }}
          aria-label="部门范围"
          popupMatchSelectWidth={false}
        />
        <ProfileToolbar
          keyword={keyword}
          onKeywordInput={debouncedSetKeyword}
          onKeywordCommit={handleKeywordCommit}
          status={status}
          onStatusChange={(value) => setStatus(value || '')}
          filterCount={activeFilterCount}
          onToggleFilter={() => setFilterOpen((v) => !v)}
        />
        <div className="ml-auto">
          <ColumnSettings
            hiddenSet={columnSettings.hiddenSet}
            hiddenCount={columnSettings.hiddenCount}
            onChange={columnSettings.setHiddenKeys}
            onShowCommon={columnSettings.showCommon}
            onShowAll={columnSettings.showAll}
          />
        </div>
      </div>

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
        hiddenColumns={columnSettings.hiddenSet}
      />

      {!syncInfo && (
        <EmployeeForm
          open={formOpen}
          employee={editingEmployee}
          onClose={() => setFormOpen(false)}
          onSuccess={() => refreshList()}
        />
      )}
    </div>
  )
}
