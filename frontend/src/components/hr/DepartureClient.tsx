'use client'

// 离职台账：结果数据（飞书「离职人员管理表」同步 + 平台离职办理办结回写），按工号挂最近一张办结单，
// 带出办理状态 / 证明开具签收 / 四部门清退结算。
// 筛选、字段勾选导出、保存视图、导出记录见 ./departure/ 下的四个组件；流程操作在办理抽屉里。
// 还没发起办理的行可以直接「发起办理」：人、离职日期、离职类型都从这一行带出，不用重新填。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, App as AntdApp, Button, DatePicker, Descriptions, Form, Input, Modal, Popconfirm, Select, Space,
  Table, Tag, Tooltip, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import {
  CloudSyncOutlined, DeleteOutlined, DownloadOutlined, EyeOutlined, HistoryOutlined, ImportOutlined,
  PlusOutlined, SendOutlined,
} from '@ant-design/icons'
import type { ClearanceCategory, ClearanceSummary, DepartureExportColumnCatalog, DepartureLedgerFilters, DepartureLedgerRow, DepartureLedgerSort, DepartureRecord, DepartureSavedView, Employee } from '@/types/hr'
import {
  createDepartureRecord,
  deleteDepartureRecordAction,
  deleteDepartureView,
  exportDepartureLedger,
  fetchDepartureExportColumns,
  fetchDepartureLedgerFilterOptions,
  fetchDepartureSavedViews,
  fetchDepartmentsAction,
  fetchEmployeesAction,
  previewDepartureCertificate,
  queryDepartureLedger,
  saveDepartureView,
  sendDepartureCertificate,
  triggerEmployeeSync,
  updateDepartureView,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { LedgerImportModal, OffboardingCaseDrawer } from '@/components/hr'
import { useHasPermission } from '@/hooks/hr'
import PageHeader from './PageHeader'
import OffboardingNewCaseModal, { type OffboardingCasePrefill } from './OffboardingNewCaseModal'
import styles from './lifecycleTable.module.css'
import { DEPARTURE_TYPE_OPTIONS, DEPARTURE_TYPE_TAG_COLORS, OFFBOARDING_STATUS_TAG_COLORS } from '@/lib/hr'
import DepartureExportLogDrawer from './departure/DepartureExportLogDrawer'
import DepartureExportModal from './departure/DepartureExportModal'
import DepartureFilterBar from './departure/DepartureFilterBar'
import DepartureViewControls from './departure/DepartureViewControls'

const { Text } = Typography

/** 离职台账页的同步状态（服务端注入；绑定离职表后页面转只读展示） */
export interface DepartureSyncInfo {
  departure_table_name: string
  last_sync_at: string | null
}

const SORT: Required<DepartureLedgerSort> = { sort_by: 'offboarding_date', sort_order: 'desc' }

function formatSyncTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ') : '从未同步'
}

/** 去掉空值：保存视图、留痕、判断「是否改过」都用这个口径 */
function compact(filters: DepartureLedgerFilters): DepartureLedgerFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}

function fmtTime(value?: string | null): string {
  // 按本地时区格式化：后端给的是带 +00:00 的 UTC 时间串，直接截取会差 8 小时
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'
}

/** 清退结算摘要：金额为 0 的不显示（「扣 0，补 0」是噪音） */
function clearanceText(bucket: ClearanceSummary): string {
  const parts = [`已确认 ${bucket.done}/${bucket.total}`]
  if (bucket.deduction) parts.push(`扣 ${bucket.deduction}`)
  if (bucket.supplement) parts.push(`补 ${bucket.supplement}`)
  return parts.join('，')
}

const CLEARANCE_LABELS: Record<ClearanceCategory, string> = {
  admin: '行政后勤部', finance: '财务部', hr: '人力资源部', work: '工作部门',
}

interface CreateFormValues {
  employee: string
  offboarding_date?: Dayjs
  offboarding_type?: string
  reason?: string
}

interface DeptEmployeeOption {
  value: string
  label: string
  name: string
  position?: string
}

export default function DepartureClient({
  initialRecords,
  initialTotal,
  syncInfo,
  refreshKey = 0,
}: {
  initialRecords: DepartureRecord[]
  initialTotal: number
  /** 绑定飞书离职人员管理表后传入：隐藏本地新建/删除，展示立即同步入口 */
  syncInfo?: DepartureSyncInfo
  /** 外层通知刷新（办理页推进了流程）：数字变了就重拉本页 */
  refreshKey?: number
}) {
  const { message } = AntdApp.useApp()
  const [rows, setRows] = useState<DepartureLedgerRow[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const loadSeq = useRef(0)

  const [filters, setFilters] = useState<DepartureLedgerFilters>({})
  const [keywordInput, setKeywordInput] = useState('')
  // 服务端排序：分页在服务端，前端 sorter 只会重排当前页
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend'>('descend')
  const [filterOptions, setFilterOptions] = useState<Awaited<ReturnType<typeof fetchDepartureLedgerFilterOptions>>>({})

  const [views, setViews] = useState<DepartureSavedView[]>([])
  const [viewsLoaded, setViewsLoaded] = useState(false)
  const [activeViewId, setActiveViewId] = useState<string | null>(null)
  const [catalog, setCatalog] = useState<DepartureExportColumnCatalog | null>(null)
  const [exportColumns, setExportColumns] = useState<string[]>([])
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [viewSaving, setViewSaving] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [selectedDept, setSelectedDept] = useState('')
  const [deptEmployees, setDeptEmployees] = useState<DeptEmployeeOption[]>([])
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRow, setDetailRow] = useState<DepartureLedgerRow | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [certOpen, setCertOpen] = useState(false)
  const [certRow, setCertRow] = useState<DepartureLedgerRow | null>(null)
  const [certEmail, setCertEmail] = useState('')
  const [certSending, setCertSending] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [caseDrawerOpen, setCaseDrawerOpen] = useState(false)
  const [newCaseOpen, setNewCaseOpen] = useState(false)
  const [newCasePrefill, setNewCasePrefill] = useState<OffboardingCasePrefill | null>(null)

  // 同步模式：数据源为飞书离职人员管理表，本地新建/删除无意义（下轮同步会覆盖）
  const syncMode = Boolean(syncInfo)
  // 水合安全的权限判断：本页在 Suspense 边界内，直接读权限 store 首帧会与 SSR 输出对不上
  const canManage = useHasPermission('hr:settings:manage')
  const canImport = useHasPermission('hr:departure:manage')
  // 发起离职办理与导入用的是同一个权限（hr:departure:manage）
  const canStartCase = canImport

  const patchFilters = useCallback((patch: Partial<DepartureLedgerFilters>) => {
    setFilters((prev) => {
      const next = { ...prev }
      for (const [key, value] of Object.entries(patch) as [keyof DepartureLedgerFilters, unknown][]) {
        if (value === undefined || value === null || value === '') delete next[key]
        else Object.assign(next, { [key]: value })
      }
      return next
    })
    setPage(1)
  }, [])

  // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    setLoading(true)
    setLoadError(null)
    try {
      const res = await queryDepartureLedger({
        ...filters,
        sort_by: SORT.sort_by,
        sort_order: sortOrder === 'ascend' ? 'asc' : 'desc',
        page,
        page_size: pageSize,
      })
      if (seq !== loadSeq.current) return
      setRows(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err) {
      if (seq === loadSeq.current) setLoadError(err instanceof Error ? err.message : '加载数据失败')
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [filters, sortOrder, page, pageSize])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 加载函数首行同步置 loading 是刻意的即时反馈
    void load()
  }, [load])

  // 外层通知刷新（办理页推进了流程后）：首次挂载的那一下（0）跳过，已有上面的首拉
  const firstRefreshKey = useRef(refreshKey)
  useEffect(() => {
    if (refreshKey === firstRefreshKey.current) return
    firstRefreshKey.current = refreshKey
    void load()
  }, [refreshKey, load])

  const refreshViews = useCallback(async () => {
    const list = await fetchDepartureSavedViews()
    setViews(list)
    return list
  }, [])

  /** 进页面：拉筛选项、导出字段、我的视图；有默认视图就套用 */
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      // 逐个兜底：任何一项失败都不影响其余（视图拉不到只是没有「我的视图」，不该挡住台账）
      const [optionList, catalogRes, deptRes, viewList] = await Promise.all([
        fetchDepartureLedgerFilterOptions().catch(() => null),
        fetchDepartureExportColumns().catch(() => null),
        fetchDepartmentsAction({ page_size: 200 }).catch(() => null),
        fetchDepartureSavedViews().catch(() => null),
      ])
      if (cancelled) return
      if (optionList) setFilterOptions(optionList)
      if (catalogRes) {
        setCatalog(catalogRes)
        setExportColumns(catalogRes.default_keys)
      }
      if (deptRes) {
        setDepartments((deptRes.data || []).map((d: { name: string }) => ({ value: d.name, label: d.name })))
      }
      if (viewList) {
        setViews(viewList)
        const defaultView = viewList.find((view) => view.is_default)
        if (defaultView) {
          setFilters(defaultView.filters || {})
          setKeywordInput(defaultView.filters?.keyword ?? '')
          if (defaultView.columns?.length) setExportColumns(defaultView.columns)
          setActiveViewId(defaultView.id)
        }
      }
      setViewsLoaded(true)
    })()
    return () => { cancelled = true }
  }, [])

  const activeView = views.find((view) => view.id === activeViewId) ?? null
  const dirty = activeView !== null && JSON.stringify(compact(filters)) !== JSON.stringify(compact(activeView.filters || {}))
  const filterCount = useMemo(() => Object.keys(compact(filters)).length, [filters])

  const applyView = (view: DepartureSavedView | null) => {
    setActiveViewId(view?.id ?? null)
    if (!view) return
    setFilters(view.filters || {})
    setKeywordInput(view.filters?.keyword ?? '')
    if (view.columns?.length) setExportColumns(view.columns)
    setPage(1)
  }

  const clearFilters = () => {
    patchFilters({
      keyword: undefined, department: undefined, position: undefined, offboarding_type: undefined,
      offboarding_reason: undefined, gender: undefined, education: undefined, employee_category: undefined,
      offboarding_date_from: undefined, offboarding_date_to: undefined, approval_status: undefined,
      cert_issued: undefined, cert_signed: undefined,
    })
    setKeywordInput('')
  }

  const saveView = async (input: { name: string; isDefault: boolean; overwrite: boolean }) => {
    const payload = { name: input.name, filters: compact(filters), columns: exportColumns, is_default: input.isDefault }
    setViewSaving(true)
    try {
      const res = input.overwrite && activeView
        ? await updateDepartureView(activeView.id, payload)
        : await saveDepartureView(payload)
      setActiveViewId(res.data.id)
      await refreshViews()
      message.success('视图已保存')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存视图失败')
      throw err
    } finally {
      setViewSaving(false)
    }
  }

  const renameView = async (view: DepartureSavedView, name: string) => {
    try {
      await updateDepartureView(view.id, { name, filters: view.filters, columns: view.columns, is_default: view.is_default })
      await refreshViews()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重命名失败')
      throw err
    }
  }

  const deleteView = async (view: DepartureSavedView) => {
    try {
      await deleteDepartureView(view.id)
      if (activeViewId === view.id) setActiveViewId(null)
      await refreshViews()
      message.success('视图已删除')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除视图失败')
    }
  }

  const setDefaultView = async (view: DepartureSavedView) => {
    try {
      await updateDepartureView(view.id, { name: view.name, filters: view.filters, columns: view.columns, is_default: true })
      await refreshViews()
      message.success(`已将「${view.name}」设为默认视图`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '设置失败')
    }
  }

  const doExport = async () => {
    setExporting(true)
    try {
      const file = await exportDepartureLedger(compact(filters), exportColumns, {
        sort_order: sortOrder === 'ascend' ? 'asc' : 'desc',
      })
      downloadBase64File(file.base64, file.filename)
      message.success(`已导出 ${exportColumns.length} 个字段`)
      setExportOpen(false)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  // ─── 以下为原有的新建 / 同步 / 发证明 / 详情 ───

  const handleDeptChange = async (dept: string) => {
    setSelectedDept(dept)
    createForm.setFieldValue('employee', undefined)
    if (!dept) {
      setDeptEmployees([])
      return
    }
    try {
      const res = await fetchEmployeesAction({ department: dept, page: 1, page_size: 200 })
      setDeptEmployees((res.data || []).map((e: Employee) => ({
        value: e.id, label: `${e.employee_number} ${e.name} (${e.position || ''})`,
        name: e.name, position: e.position,
      })))
      if (!res.data?.length) message.warning(`${dept} 下暂无员工`)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载员工失败')
    }
  }

  const handleCreate = async () => {
    let values: CreateFormValues
    try {
      values = await createForm.validateFields()
    } catch {
      return
    }
    const employee = deptEmployees.find((e) => e.value === values.employee)
    setCreateLoading(true)
    try {
      await createDepartureRecord({
        name: employee?.name || '',
        department: selectedDept,
        position: employee?.position || '',
        offboarding_date: values.offboarding_date?.format('YYYY-MM-DD'),
        offboarding_type: values.offboarding_type || '辞职',
        reason: values.reason || '',
      })
      message.success('离职记录创建成功')
      setCreateOpen(false)
      createForm.resetFields()
      void load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreateLoading(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await triggerEmployeeSync()
      const dep = res.data?.departures
      if (dep?.error) {
        message.warning(`员工档案已同步，但离职台账拉取失败：${dep.error}`, 10)
      } else if (dep) {
        message.success(`同步完成：离职台账 ${dep.total ?? 0} 行（新增 ${dep.created ?? 0} / 更新 ${dep.updated ?? 0}）`)
      } else {
        message.success('同步完成')
      }
      void load()
      // 同步可能带来新的部门 / 离职类型取值，下拉选项一并刷新
      fetchDepartureLedgerFilterOptions().then(setFilterOptions).catch(() => {})
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const handlePreviewCert = async () => {
    if (!certRow) return
    // 先同步开窗再取数：await 之后的 window.open 不算用户手势，会被浏览器拦截
    const win = window.open('', '_blank')
    if (!win) {
      message.warning('浏览器拦截了预览窗口，请允许本站弹出窗口后重试')
      return
    }
    try {
      win.document.write(await previewDepartureCertificate(certRow.id))
      win.document.close()
    } catch (err) {
      win.close()
      message.error(err instanceof Error ? err.message : '预览失败')
    }
  }

  const handleSendCert = async () => {
    if (!certRow || !certEmail.trim()) return
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(certEmail.trim())) {
      message.warning('请输入正确的收件邮箱地址')
      return
    }
    setCertSending(true)
    try {
      const fd = new FormData()
      fd.append('employee_email', certEmail.trim())
      await sendDepartureCertificate(certRow.id, fd)
      message.success('离职证明已发送')
      setCertOpen(false)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '发送失败')
    } finally {
      setCertSending(false)
    }
  }

  const openCase = (row: DepartureLedgerRow) => {
    if (!row.case_id) return
    setCaseId(row.case_id)
    setCaseDrawerOpen(true)
  }

  /** 从这一行发起离职办理：人、离职日期、离职类型都带过去，不用重新填 */
  const startCase = (row: DepartureLedgerRow) => {
    if (!row.employee_id) return
    setNewCasePrefill({
      departureRecordId: row.id,
      employeeId: row.employee_id,
      employeeNumber: row.employee_number || '',
      label: `${row.employee_number || ''} ${row.name}（${row.department} / ${row.position || '-'}）`,
      offboardingDate: row.offboarding_date || dayjs().add(30, 'day').format('YYYY-MM-DD'),
      offboardingType: row.offboarding_type || '辞职',
      ledgerSynced: !!row.ledger_synced,
    })
    setNewCaseOpen(true)
  }

  const statusTag = (row: DepartureLedgerRow) => (
    <Tag color={OFFBOARDING_STATUS_TAG_COLORS[row.approval_status || ''] || 'default'}>
      {row.approval_status_label || '未发起'}
    </Tag>
  )

  const columns: ColumnsType<DepartureLedgerRow> = [
    { title: '姓名', dataIndex: 'name', key: 'name', width: 90, fixed: 'left' },
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      // 9 位工号 + 复制图标需要 130px
      width: 130,
      render: (value: string | undefined) =>
        value ? <Text copyable className="text-xs">{value}</Text> : '-',
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 150 },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 120 },
    { title: '职务', dataIndex: 'duty', key: 'duty', width: 100, render: (v: string | undefined) => v || '-' },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 110,
      sortOrder,
      sorter: true,
    },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 110,
      render: (value: string | undefined) => (
        <Tag color={DEPARTURE_TYPE_TAG_COLORS[value || ''] || 'default'}>{value || '-'}</Tag>
      ),
    },
    {
      title: '办理状态',
      key: 'approval_status',
      width: 120,
      render: (_v: unknown, row) => (
        row.case_id ? (
          <Button type="link" size="small" className="!px-0" onClick={(e) => { e.stopPropagation(); openCase(row) }}>
            {statusTag(row)}
          </Button>
        ) : (
          <Tooltip title={row.startable ? '还没发起办理：点右侧「发起办理」开始走流程' : (row.start_block_reason || '没有离职办理单')}>
            {statusTag(row)}
          </Tooltip>
        )
      ),
    },
    {
      title: '证明',
      key: 'cert',
      width: 170,
      render: (_v: unknown, row) => (
        <Space size={4}>
          {row.cert_issued ? <Tag color="success">已开具</Tag> : <Tag>未开具</Tag>}
          {row.cert_signed ? <Tag color="success">已签收</Tag> : <Tag>未签收</Tag>}
        </Space>
      ),
    },
    { title: '离职时司龄', dataIndex: 'company_tenure_at_leave', key: 'company_tenure_at_leave', width: 100 },
    { title: '入职日期', dataIndex: 'livo_entry_date', key: 'livo_entry_date', width: 110 },
    { title: '学历', dataIndex: 'education', key: 'education', width: 80 },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right',
      render: (_v: unknown, row) => {
        // 已取消的办理单不挡路：这一行还能重新发起
        const cancelled = !!row.case_id && row.approval_status === 'canceled'
        return (
          <Space size="small">
            {row.case_id && !cancelled ? (
              // 有办理单：进抽屉接着办（已办结的也能进去看证明、签名和清退结果）
              <Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => openCase(row)}>
                办理
              </Button>
            ) : row.startable && canStartCase ? (
              <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => startCase(row)}>
                {cancelled ? '重新发起' : '发起办理'}
              </Button>
            ) : (
              // 没有办理单、也没法再发起（员工已是离职状态的历史记录）：只能单独补开证明
              <Tooltip title="该员工未在系统内办理离职（历史记录）：只能单独生成并发送证明，不走清退会签流程">
                <Button
                  type="link"
                  size="small"
                  icon={<SendOutlined />}
                  onClick={() => { setCertRow(row); setCertEmail(row.phone || ''); setCertOpen(true) }}
                >
                  补开证明
                </Button>
              </Tooltip>
            )}
            <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => { setDetailRow(row); setDetailOpen(true) }}>
              详情
            </Button>
            {!syncMode && (
              <Popconfirm
                title="确认删除？"
                onConfirm={async () => {
                  try {
                    await deleteDepartureRecordAction(row.id)
                    message.success('已删除')
                    void load()
                  } catch (err) {
                    message.error(err instanceof Error ? err.message : '删除失败')
                  }
                }}
              >
                <Button type="text" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  const detailItem = (label: string, value: unknown) => ({
    key: label, label, children: (value === null || value === undefined || value === '') ? '-' : String(value),
  })

  return (
    <div className="space-y-4">
      <PageHeader
        title="离职台账"
        description={syncMode
          ? `数据来源：飞书「${syncInfo!.departure_table_name}」单向同步 · 每小时自动对账 · 上次同步：${formatSyncTime(syncInfo!.last_sync_at)}。离职日期、离职类型以飞书表为准；要在系统里走离职流程的，点该行「发起办理」。`
          : undefined}
      />

      <div className="flex flex-wrap items-center gap-3">
        {!syncMode && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); setSelectedDept(''); setDeptEmployees([]); createForm.resetFields() }}>
            新建离职
          </Button>
        )}
        {!syncMode && canImport && (
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入</Button>
        )}
        {syncMode && canManage && (
          <Tooltip title="数据来自飞书表的单向同步：增删改请在飞书表中操作，这里只读">
            <Button icon={<CloudSyncOutlined />} loading={syncing} onClick={() => void handleSync()}>
              立即同步
            </Button>
          </Tooltip>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {viewsLoaded && (
            <DepartureViewControls
              views={views}
              activeViewId={activeViewId}
              dirty={dirty}
              filterCount={filterCount}
              columnCount={exportColumns.length}
              saving={viewSaving}
              onApply={applyView}
              onSave={saveView}
              onRename={renameView}
              onDelete={deleteView}
              onSetDefault={setDefaultView}
            />
          )}
          <Button icon={<DownloadOutlined />} onClick={() => setExportOpen(true)}>
            导出Excel
          </Button>
          {canImport && (
            <Tooltip title="每次导出的操作人、时间、筛选条件与条数">
              <Button onClick={() => setLogsOpen(true)}>导出记录</Button>
            </Tooltip>
          )}
        </div>
      </div>

      <DepartureFilterBar
        filters={filters}
        keywordInput={keywordInput}
        onKeywordInput={setKeywordInput}
        options={filterOptions}
        onChange={patchFilters}
        onClear={clearFilters}
      />

      {loadError && <Alert type="error" showIcon title={loadError} />}

      <Table<DepartureLedgerRow>
        className={styles.tableLg}
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={loading}
        // 排序循环须为「降序→升序→取消」：antd 默认是升→降→取消，从默认的降序点一下会落到「取消」
        sortDirections={['descend', 'ascend']}
        onChange={(_pagination, _filters, sorter) => {
          const order = (Array.isArray(sorter) ? sorter[0] : sorter)?.order
          setSortOrder(order === 'ascend' ? 'ascend' : 'descend')
          setPage(1)
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        scroll={{ x: 1650 }}
      />

      <Modal title="新建离职记录" open={createOpen} onOk={() => void handleCreate()} onCancel={() => setCreateOpen(false)}
        confirmLoading={createLoading} destroyOnHidden width={500}>
        <Form form={createForm} layout="vertical">
          <Form.Item label="选择部门" required>
            <Select placeholder="先选部门" options={departments} value={selectedDept || undefined}
              onChange={(v) => void handleDeptChange(v)} allowClear />
          </Form.Item>
          <Form.Item name="employee" label="选择员工" rules={[{ required: true, message: '请选择员工' }]}>
            <Select placeholder="选完部门再选员工" options={deptEmployees} disabled={!selectedDept}
              showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item name="offboarding_date" label="离职日期" rules={[{ required: true }]}>
            <DatePicker className="w-full" />
          </Form.Item>
          <Form.Item name="offboarding_type" label="离职类型" initialValue="辞职">
            <Select options={DEPARTURE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item name="reason" label="离职原因">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="补开离职证明（历史记录）" open={certOpen} onCancel={() => setCertOpen(false)}
        footer={[
          <Button key="preview" onClick={() => void handlePreviewCert()}>预览</Button>,
          <Button key="send" type="primary" loading={certSending} onClick={() => void handleSendCert()}>发送</Button>,
        ]}>
        <div className="space-y-3 py-2">
          <div>收件人：<b>{certRow?.name}</b>（{certRow?.department} / {certRow?.position}）</div>
          <div className="text-[12px] text-[var(--color-slate)]">
            该员工没有在系统里办离职：这里只生成证明并发到邮箱，不走清退会签，也不会回写办理状态。
          </div>
          <Input placeholder="请输入收件邮箱" value={certEmail} onChange={(e) => setCertEmail(e.target.value)} type="email" />
        </div>
      </Modal>

      <Modal title={`离职详情${detailRow?.name ? ` — ${detailRow.name}` : ''}`}
        open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={760}>
        {detailRow && (
          <div className="space-y-4">
            <Descriptions title="基本信息" size="small" bordered column={2}
              items={[
                detailItem('工号', detailRow.employee_number),
                detailItem('姓名', detailRow.name),
                detailItem('部门', detailRow.department),
                detailItem('岗位', detailRow.position),
                detailItem('职务', detailRow.duty),
                detailItem('职级', [detailRow.rank, detailRow.rank_category].filter(Boolean).join(' / ')),
                detailItem('性别', detailRow.gender),
                detailItem('员工性质', detailRow.employee_category),
                detailItem('统计类别', detailRow.status_category),
              ]} />
            <Descriptions title="日期与司龄" size="small" bordered column={2}
              items={[
                detailItem('入职日期', detailRow.livo_entry_date),
                detailItem('离职日期', detailRow.offboarding_date),
                detailItem('参加工作时间', detailRow.work_start_date),
                detailItem('离职时司龄', detailRow.company_tenure_at_leave),
                detailItem('合同期限', detailRow.contract_type),
                detailItem('合同起止', [detailRow.contract_start_date, detailRow.contract_end_date].filter(Boolean).join(' ~ ')),
              ]} />
            <Descriptions title="离职信息" size="small" bordered column={2}
              items={[
                detailItem('离职类型', detailRow.offboarding_type),
                detailItem('离职原因', Array.isArray(detailRow.offboarding_reason) ? detailRow.offboarding_reason.join('、') : detailRow.offboarding_reason),
                detailItem('任命与岗位调动', detailRow.transfer_history),
                detailItem('证书', detailRow.certificates),
              ]} />
            <Descriptions title="办理流程" size="small" bordered column={2}
              items={[
                detailItem('申请编号', detailRow.case_no),
                { key: 'status', label: '办理状态', children: statusTag(detailRow) },
                detailItem('HR 负责人', detailRow.hr_owner),
                detailItem('证明开具时间', fmtTime(detailRow.cert_issued_at)),
                detailItem('签收时间', fmtTime(detailRow.cert_signed_at)),
                detailItem('签收人', detailRow.cert_sign_name),
                detailItem('签收方式', detailRow.cert_signed
                  ? (detailRow.has_sign_image ? '当面手写签名' : '纸质签收登记')
                  : '未签收'),
                ...(['admin', 'finance', 'hr', 'work'] as ClearanceCategory[]).map((category) => {
                  const bucket = detailRow.clearance?.[category]
                  return detailItem(
                    `${CLEARANCE_LABELS[category]}清退`,
                    bucket && bucket.total ? clearanceText(bucket) : '无清退明细',
                  )
                }),
              ]} />
            <Descriptions title="学历" size="small" bordered column={2}
              items={[
                detailItem('学历', detailRow.education),
                detailItem('学位类型', detailRow.degree_type),
                detailItem('毕业院校', detailRow.school),
                detailItem('专业', detailRow.major),
                detailItem('全日制', detailRow.classification),
              ]} />
            <Descriptions title="个人与联系（敏感字段按权限脱敏）" size="small" bordered column={2}
              items={[
                detailItem('身份证号', detailRow.id_card),
                detailItem('身份证有效期', detailRow.id_card_expiry),
                detailItem('籍贯', detailRow.native_place),
                detailItem('民族', detailRow.ethnicity),
                detailItem('户口类型', detailRow.household_type),
                detailItem('婚姻状况', detailRow.marital_status),
                detailItem('政治面貌', detailRow.political_status),
                detailItem('居住地址', detailRow.residence_address),
                detailItem('联系电话', detailRow.phone),
                detailItem('银行卡号', detailRow.bank_account),
                detailItem('紧急联系人', [
                  detailRow.emergency_contact_name,
                  detailRow.emergency_contact_relation,
                  detailRow.emergency_contact_phone,
                ].filter(Boolean).join(' / ')),
              ]} />
          </div>
        )}
      </Modal>

      <LedgerImportModal
        open={importOpen}
        ledger="departure"
        label="离职台账"
        onClose={() => setImportOpen(false)}
        onSuccess={() => void load()}
      />

      {catalog && (
        <DepartureExportModal
          open={exportOpen}
          columns={catalog.columns}
          defaultKeys={catalog.default_keys}
          selected={exportColumns}
          onChange={setExportColumns}
          loading={exporting}
          onClose={() => setExportOpen(false)}
          onExport={() => void doExport()}
        />
      )}
      <DepartureExportLogDrawer open={logsOpen} onClose={() => setLogsOpen(false)} />
      <OffboardingCaseDrawer
        open={caseDrawerOpen}
        caseId={caseId}
        onClose={() => setCaseDrawerOpen(false)}
        onChanged={() => void load()}
      />
      <OffboardingNewCaseModal
        open={newCaseOpen}
        prefill={newCasePrefill}
        onClose={() => setNewCaseOpen(false)}
        onCreated={(id) => {
          // 发起后原地接着办：刷新台账，直接打开这张办理单的抽屉
          setNewCaseOpen(false)
          void load()
          setCaseId(id)
          setCaseDrawerOpen(true)
        }}
      />
    </div>
  )
}
