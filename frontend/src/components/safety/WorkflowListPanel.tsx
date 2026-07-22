'use client'

import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  Table,
  Input,
  Button,
  Space,
  App,
  Modal,
  Typography,
  Checkbox,
  Popover,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  FilterOutlined,
  CloseCircleOutlined,
  CaretUpFilled,
  CaretDownFilled,
  ClusterOutlined,
} from '@ant-design/icons'
import {
  getHazardIdentifications,
  deleteHazardIdentification,
  getHIStats,
} from '@/actions/safety'
import type { HazardIdentification, HazardIdentificationStats } from '@/types/safety'
import {
  AI_NODE_PROGRESS_OPTIONS,
  OVERALL_STATUS_OPTIONS_HI,
} from '@/types/safety'
import HazardIdentificationDrawer from './HazardIdentificationDrawer'
import HazardIdentificationBatchDrawer from './HazardIdentificationBatchDrawer'
import BatchProgressPanel from './BatchProgressPanel'

import { statusPill, actionLink } from '@/components/safety/shared-styles'

const { Text } = Typography

// ── AI 进度颜色配置 ──
const PROGRESS_COLOR_CONFIG: Record<string, { color: string; bg: string }> = {
  pending_input:    { color: '#5d5b54', bg: '#f0eeec' },
  pending_script1:  { color: '#0075de', bg: '#dcecfa' },
  pending_script2:  { color: '#0075de', bg: '#dcecfa' },
  pending_script3:  { color: '#0075de', bg: '#dcecfa' },
  pending_script4:  { color: '#0075de', bg: '#dcecfa' },
  pending_script5:  { color: '#0075de', bg: '#dcecfa' },
  pending_script6:  { color: '#0075de', bg: '#dcecfa' },
  pending_script7:  { color: '#0075de', bg: '#dcecfa' },
  completed:        { color: '#1aae39', bg: '#d9f3e1' },
}

// ── 状态颜色配置 ──
const STATUS_COLOR_CONFIG: Record<string, { color: string; bg: string }> = {
  draft:        { color: '#5d5b54', bg: '#f0eeec' },
  in_progress:  { color: '#0075de', bg: '#dcecfa' },
  completed:    { color: '#1aae39', bg: '#d9f3e1' },
  cancelled:    { color: '#e03131', bg: '#fde0ec' },
}

// ── 统计药丸配置 ──
const STATS_PILLS = [
  { key: '',            label: '全部',   dotColor: '#1a1a1a', filterable: true  },
  { key: 'draft',       label: '草稿',   dotColor: '#5d5b54', filterable: true  },
  { key: 'in_progress', label: '进行中', dotColor: '#0075de', filterable: true  },
  { key: 'completed',   label: '已完成', dotColor: '#1aae39', filterable: true  },
]

// ── 可筛选字段配置 ──
interface FilterFieldConfig {
  key: string
  label: string
  type?: 'text' | 'select'
  options: Array<{ value: string; label: string }>
}
const FILTER_FIELDS: FilterFieldConfig[] = [
  {
    key: 'ai_node_progress',
    label: 'AI 进度',
    options: AI_NODE_PROGRESS_OPTIONS.filter((o) => o.value !== 'pending_input'),
  },
  {
    key: 'department',
    label: '部门',
    type: 'text' as const,
    options: [],
  },
]

export default function WorkflowListPanel() {
  const router = useRouter()
  const { message: msgApi } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<HazardIdentification[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<HazardIdentificationStats>({
    total_draft: 0,
    total_in_progress: 0,
    total_pending_review: 0,
    total_completed: 0,
  })
  const [queryParams, setQueryParams] = useState({ page: 1, page_size: 20 })
  const [keyword, setKeyword] = useState('')
  const [searchApplied, setSearchApplied] = useState(false)
  const searchKeywordRef = useRef('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [progressFilter, setProgressFilter] = useState<string | undefined>()
  const [deptFilter, setDeptFilter] = useState<string | undefined>()

  // ── 排序状态 ──
  const [sortField, setSortField] = useState<string | undefined>()
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend' | undefined>()

  // ── 筛选弹出框状态 ──
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [pendingFilterField, setPendingFilterField] = useState<string | null>(null)

  // ── 批量选择 & 删除 ──
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [deleting, setDeleting] = useState(false)
  const [hoveredRowId, setHoveredRowId] = useState<string | null>(null)

  // ── 筛选栏滚动容器 ref ──
  const filterScrollRef = useRef<HTMLDivElement>(null)

  // ── 新建抽屉状态 ──
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [batchDrawerOpen, setBatchDrawerOpen] = useState(false)

  // ── URL 参数 ──
  const searchParams = useSearchParams()
  const activeBatchId = searchParams.get('batch_id')

  // ── 活跃筛选条件 ──
  const activeFilters = useMemo(() => {
    const list: { key: string; fieldLabel: string; value: string; valueLabel: string }[] = []
    if (progressFilter) {
      const opt = AI_NODE_PROGRESS_OPTIONS.find((o) => o.value === progressFilter)
      list.push({ key: 'ai_node_progress', fieldLabel: 'AI进度', value: progressFilter, valueLabel: opt?.label || progressFilter })
    }
    if (deptFilter) {
      list.push({ key: 'department', fieldLabel: '部门', value: deptFilter, valueLabel: deptFilter })
    }
    return list
  }, [progressFilter, deptFilter])

  // 移除单个筛选条件
  const removeFilter = useCallback((key: string) => {
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    switch (key) {
      case 'ai_node_progress': setProgressFilter(undefined); break
      case 'department': setDeptFilter(undefined); break
    }
  }, [queryParams.page_size, setQueryParams])

  // 清除所有筛选
  const clearAllFilters = useCallback(() => {
    setProgressFilter(undefined)
    setDeptFilter(undefined)
    setStatusFilter(undefined)
    setKeyword('')
    setSearchApplied(false)
    setQueryParams({ page: 1, page_size: queryParams.page_size })
  }, [queryParams.page_size, setQueryParams])

  // 处理筛选字段选择
  const handleFilterFieldSelect = (fieldKey: string) => {
    setPendingFilterField(fieldKey)
  }

  const handleFilterValueSelect = (fieldKey: string, value: string) => {
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    switch (fieldKey) {
      case 'ai_node_progress': setProgressFilter(value); break
      case 'department': setDeptFilter(value); break
    }
    setPendingFilterField(null)
    setFilterPopoverOpen(false)
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await getHazardIdentifications({
        ...queryParams,
        keyword: searchKeywordRef.current || undefined,
        overall_status: statusFilter,
        ai_node_progress: progressFilter,
        department: deptFilter,
        batch_id: activeBatchId || undefined,
      })
      if (res.code === 200) {
        let list = (res.data as HazardIdentification[]) || []
        // 客户端排序
        if (sortField && sortOrder) {
          list = [...list].sort((a: any, b: any) => {
            const aVal = a[sortField] ?? ''
            const bVal = b[sortField] ?? ''
            const cmp = String(aVal).localeCompare(String(bVal), 'zh-CN')
            return sortOrder === 'ascend' ? cmp : -cmp
          })
        }
        setData(list)
        setTotal(res.meta?.total || 0)
      }
    } catch {
      msgApi.error('加载列表失败')
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const res = await getHIStats()
      if (res.code === 200 && res.data) {
        setStats(res.data as HazardIdentificationStats)
      }
    } catch { /* 静默失败 */ }
  }

  useEffect(() => { loadStats() }, [])

  useEffect(() => {
    setSelectedRowKeys([])
    loadData()
  }, [queryParams.page, queryParams.page_size, statusFilter, progressFilter, deptFilter])

  // 排序变化时重新加载
  useEffect(() => {
    if (sortField) {
      loadData()
    }
  }, [sortField, sortOrder])

  const handleSearch = () => {
    searchKeywordRef.current = keyword
    setSearchApplied(true)
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    loadData()
  }

  const handleSearchBack = () => {
    searchKeywordRef.current = ''
    setKeyword('')
    setSearchApplied(false)
    loadData()
  }

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该危险源辨识记录吗？',
      onOk: async () => {
        const res = await deleteHazardIdentification(id)
        if (res.code === 200) {
          msgApi.success('删除成功')
          loadData()
          loadStats()
        } else {
          msgApi.error(res.message || '删除失败')
        }
      },
    })
  }

  // ── 批量删除 ──
  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条记录吗？此操作不可撤销。`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setDeleting(true)
        let succeeded = 0
        let failed = 0
        for (const id of selectedRowKeys as string[]) {
          try {
            const res = await deleteHazardIdentification(id)
            if (res.code === 200) succeeded++; else failed++
          } catch { failed++ }
        }
        if (failed === 0) {
          msgApi.success(`成功删除 ${succeeded} 条记录`)
        } else {
          msgApi.warning(`删除完成：${succeeded} 条成功，${failed} 条失败`)
        }
        setSelectedRowKeys([])
        await loadData()
        loadStats()
        setDeleting(false)
      },
    })
  }

  // ── 排序切换 ──
  const handleSort = (field: string) => {
    if (sortField !== field) {
      setSortField(field)
      setSortOrder('ascend')
    } else if (sortOrder === 'ascend') {
      setSortOrder('descend')
    } else if (sortOrder === 'descend') {
      setSortField(undefined)
      setSortOrder(undefined)
    }
  }

  // ── 排序图标 ──
  const renderSortIcon = (field: string) => {
    const isActive = sortField === field
    return (
      <span style={{ display: 'inline-flex', flexDirection: 'column', marginLeft: 2, lineHeight: 1 }}>
        <CaretUpFilled style={{
          fontSize: 8,
          color: isActive && sortOrder === 'ascend' ? '#5645d4' : '#c8c4be',
          marginBottom: -2,
        }} />
        <CaretDownFilled style={{
          fontSize: 8,
          color: isActive && sortOrder === 'descend' ? '#5645d4' : '#c8c4be',
        }} />
      </span>
    )
  }

  // ── 统计药丸计数 ──
  const getPillCount = (key: string): number => {
    switch (key) {
      case '': return stats.total_draft + stats.total_in_progress + stats.total_pending_review + stats.total_completed
      case 'draft': return stats.total_draft
      case 'in_progress': return stats.total_in_progress
      case 'completed': return stats.total_completed
      default: return 0
    }
  }

  const handlePillClick = (pill: typeof STATS_PILLS[number]) => {
    if (!pill.filterable) return
    if (pill.key === '') {
      setStatusFilter(undefined)
    } else {
      setStatusFilter(statusFilter === pill.key ? undefined : pill.key)
    }
  }

  const getStatusTag = (status: string) => {
    const cfg = STATUS_COLOR_CONFIG[status]
    const opt = OVERALL_STATUS_OPTIONS_HI.find((o) => o.value === status)
    if (!cfg) return <span style={statusPill('#5d5b54', '#f0eeec')}>{opt?.label || status}</span>
    return <span style={statusPill(cfg.color, cfg.bg)}>{opt?.label || status}</span>
  }

  const getProgressTag = (progress: string) => {
    const cfg = PROGRESS_COLOR_CONFIG[progress]
    const opt = AI_NODE_PROGRESS_OPTIONS.find((o) => o.value === progress)
    if (!cfg) return <span style={statusPill('#5d5b54', '#f0eeec')}>{opt?.label || progress}</span>
    return <span style={statusPill(cfg.color, cfg.bg)}>{opt?.label || progress}</span>
  }

  // ── 表格列定义 ──
  const columns: ColumnsType<HazardIdentification> = [
    // ── 隐藏式复选框列 ──
    {
      title: '',
      key: '__row_select__',
      width: 48,
      fixed: 'start',
      align: 'center',
      render: (_: unknown, record: HazardIdentification, index: number) => {
        const isSelected = selectedRowKeys.includes(record.id)
        const isHovered = hoveredRowId === record.id
        const rowNum = ((queryParams.page || 1) - 1) * (queryParams.page_size || 20) + index + 1

        const handleToggle = () => {
          setSelectedRowKeys((prev) =>
            prev.includes(record.id)
              ? prev.filter((k) => k !== record.id)
              : [...prev, record.id]
          )
        }

        if (isSelected) {
          return (
            <Checkbox
              checked
              onChange={handleToggle}
              style={{ zIndex: 2 }}
            />
          )
        }

        return (
          <span
            style={{
              position: 'relative',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 24,
              height: 24,
              cursor: 'pointer',
            }}
            onClick={handleToggle}
          >
            <span
              style={{
                fontSize: 12,
                color: '#a4a097',
                fontWeight: 400,
                transition: 'opacity 0.12s ease',
                opacity: isHovered ? 0 : 1,
                position: 'absolute',
              }}
            >
              {rowNum}
            </span>
            <span
              style={{
                transition: 'opacity 0.12s ease',
                opacity: isHovered ? 1 : 0,
                position: 'absolute',
              }}
            >
              <Checkbox checked={false} />
            </span>
          </span>
        )
      },
    },
    {
      title: '编号',
      dataIndex: 'hazard_id_no',
      key: 'hazard_id_no',
      width: 120,
      sorter: false,
      render: (text: string, record: HazardIdentification) => (
        <span
          style={{ color: '#0075de', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
          onClick={() => router.push(`/safety/hazard-identification/${record.id}`)}
        >
          {text}
        </span>
      ),
    },
    {
      title: (
        <span
          onClick={() => handleSort('department')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          部门{renderSortIcon('department')}
        </span>
      ),
      dataIndex: 'department',
      key: 'department',
      width: 100,
      sorter: false,
      ellipsis: true,
    },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 90,
      ellipsis: true,
    },
    {
      title: '生产步骤',
      dataIndex: 'production_step',
      key: 'production_step',
      width: 160,
      ellipsis: true,
    },
    {
      title: (
        <span
          onClick={() => handleSort('ai_node_progress')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          当前步骤{renderSortIcon('ai_node_progress')}
        </span>
      ),
      dataIndex: 'ai_node_progress',
      key: 'ai_node_progress',
      width: 140,
      sorter: false,
      render: (v: string) => getProgressTag(v),
    },
    {
      title: (
        <span
          onClick={() => handleSort('overall_status')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          状态{renderSortIcon('overall_status')}
        </span>
      ),
      dataIndex: 'overall_status',
      key: 'overall_status',
      width: 80,
      sorter: false,
      render: (v: string) => getStatusTag(v),
    },
    {
      title: (
        <span
          onClick={() => handleSort('created_at')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          创建时间{renderSortIcon('created_at')}
        </span>
      ),
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      sorter: false,
      render: (v: string) => {
        if (!v) return <span style={{ color: '#a4a097' }}>-</span>
        return <span style={{ fontSize: 13 }}>{new Date(v).toLocaleString('zh-CN', {
          month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
        })}</span>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      fixed: 'right',
      align: 'center',
      render: (_, r) => {
        if (r.overall_status === 'draft' || r.overall_status === 'cancelled') {
          return (
            <Space size={12}>
              <span
                role="button"
                onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
                style={actionLink('#0075de')}
              >
                <EyeOutlined />查看
              </span>
              <span
                role="button"
                onClick={() => handleDelete(r.id)}
                style={actionLink('#e03131')}
              >
                <DeleteOutlined />删除
              </span>
            </Space>
          )
        }
        if (r.overall_status === 'in_progress') {
          return (
            <span
              role="button"
              onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
              style={actionLink('#0075de')}
            >
              <PlayCircleOutlined />继续
            </span>
          )
        }
        return (
          <span
            role="button"
            onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
            style={actionLink('#0075de')}
          >
            <EyeOutlined />查看
          </span>
        )
      },
    },
  ]

  // ── 筛选弹出内容 ──
  const filterPopoverContent = (
    <div style={{ minWidth: 220 }}>
      {pendingFilterField ? (
        // ── 选择筛选值 ──
        <div>
          <div
            onClick={() => setPendingFilterField(null)}
            style={{
              cursor: 'pointer',
              fontSize: 13,
              color: '#5645d4',
              marginBottom: 8,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            ← 返回
          </div>
          <div style={{ fontSize: 12, color: '#787671', marginBottom: 8 }}>
            {FILTER_FIELDS.find((f) => f.key === pendingFilterField)?.label}
          </div>
          {FILTER_FIELDS.find((f) => f.key === pendingFilterField)?.type === 'text' ? (
            <Input
              placeholder="请输入部门名称"
              onPressEnter={(e) => {
                const val = (e.target as HTMLInputElement).value.trim()
                if (val) handleFilterValueSelect(pendingFilterField!, val)
              }}
              style={{ width: '100%' }}
              autoFocus
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {FILTER_FIELDS
                .find((f) => f.key === pendingFilterField)
                ?.options.map((opt) => (
                  <div
                    key={opt.value}
                    onClick={() => handleFilterValueSelect(pendingFilterField!, opt.value)}
                    style={{
                      padding: '6px 12px',
                      cursor: 'pointer',
                      borderRadius: 6,
                      fontSize: 13,
                      color: '#1a1a1a',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#f5f3f0' }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
                  >
                    {opt.label}
                  </div>
                ))}
            </div>
          )}
        </div>
      ) : (
        // ── 选择筛选字段 ──
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1a1a', marginBottom: 8 }}>
            添加筛选条件
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {FILTER_FIELDS.map((field) => {
              const isApplied = activeFilters.some((f) => f.key === field.key)
              return (
                <div
                  key={field.key}
                  onClick={() => !isApplied && handleFilterFieldSelect(field.key)}
                  style={{
                    padding: '6px 12px',
                    cursor: isApplied ? 'default' : 'pointer',
                    borderRadius: 6,
                    fontSize: 13,
                    color: isApplied ? '#a4a097' : '#1a1a1a',
                    transition: 'background 0.12s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                  onMouseEnter={(e) => {
                    if (!isApplied) (e.currentTarget as HTMLDivElement).style.background = '#f5f3f0'
                  }}
                  onMouseLeave={(e) => {
                    if (!isApplied) (e.currentTarget as HTMLDivElement).style.background = 'transparent'
                  }}
                >
                  <span>{field.label}</span>
                  {isApplied && <span style={{ fontSize: 11, color: '#a4a097' }}>已添加</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div style={{ padding: 24 }}>
      {/* ── 页面头部 ── */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', margin: 0, marginBottom: 4, lineHeight: 1.3 }}>
          危险源辨识工作流
        </h2>
        <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
          AI 7步危险源辨识与风险评价管理
        </p>
      </div>

      {/* ── 统计药丸 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {STATS_PILLS.map((pill) => {
          const pillKey = pill.key || 'all'
          const isActive = pill.key === ''
            ? statusFilter === undefined
            : pill.filterable && statusFilter === pill.key
          const count = getPillCount(pill.key)
          return (
            <button
              key={pillKey}
              type="button"
              onClick={() => handlePillClick(pill)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                cursor: pill.filterable ? 'pointer' : 'default',
                background: isActive ? '#f0eeec' : 'transparent',
                border: isActive ? '1px solid #c8c4be' : '1px solid transparent',
                borderRadius: 20,
                padding: '4px 12px',
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? '#1a1a1a' : pill.filterable ? '#5d5b54' : '#a4a097',
                transition: 'all 0.15s ease',
                fontFamily: 'inherit',
                lineHeight: '20px',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: pill.dotColor,
                  flexShrink: 0,
                  opacity: pill.filterable ? 1 : 0.5,
                }}
              />
              {pill.label}
              <span style={{ fontWeight: 600, color: pill.filterable ? pill.dotColor : '#a4a097', marginLeft: 2 }}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* ── 多维筛选栏 ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 16,
          minHeight: 32,
        }}
      >
        {/* 搜索框（固定在左侧） */}
        <div style={{ display: 'flex', alignItems: 'stretch', flexShrink: 0 }}>
          <Input
            placeholder="搜索编号/部门/岗位"
            prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
            style={{
              width: 220,
              height: 40,
              borderTopRightRadius: 0,
              borderBottomRightRadius: 0,
              borderRight: 'none',
            }}
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              if (!e.target.value && searchApplied) {
                handleSearchBack()
              }
            }}
            onPressEnter={handleSearch}
            allowClear
          />
          {!searchApplied ? (
            <Button
              onClick={handleSearch}
              disabled={!keyword.trim()}
              style={{
                borderTopLeftRadius: 0,
                borderBottomLeftRadius: 0,
                height: 40,
                padding: '4px 16px',
                marginLeft: 0,
              }}
            >
              搜索
            </Button>
          ) : (
            <Button
              onClick={handleSearchBack}
              style={{
                borderTopLeftRadius: 0,
                borderBottomLeftRadius: 0,
                height: 32,
                padding: '4px 16px',
                marginLeft: 0,
                color: '#5645d4',
                borderColor: '#5645d4',
              }}
            >
              返回
            </Button>
          )}
        </div>

        {/* 筛选 chips 横向滚动容器 */}
        <div
          ref={filterScrollRef}
          style={{
            flex: 1,
            overflowX: 'auto',
            overflowY: 'hidden',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            paddingBottom: 0,
            msOverflowStyle: 'none',
            scrollbarWidth: 'thin',
          }}
        >
          {/* 活跃筛选条件 chips */}
          {activeFilters.map((f) => (
            <div
              key={f.key}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 10px',
                borderRadius: 20,
                background: '#e6e0f5',
                border: '1px solid #cdc4e8',
                fontSize: 13,
                lineHeight: '20px',
                whiteSpace: 'nowrap',
                flexShrink: 0,
                cursor: 'default',
              }}
            >
              <span style={{ color: '#787671', fontSize: 12 }}>{f.fieldLabel}:</span>
              <span style={{ color: '#391c57', fontWeight: 600 }}>{f.valueLabel}</span>
              <span
                role="button"
                onClick={() => removeFilter(f.key)}
                style={{
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  background: '#391c57',
                  color: '#fff',
                  fontSize: 10,
                  flexShrink: 0,
                  lineHeight: 1,
                }}
              >
                ✕
              </span>
            </div>
          ))}

          {/* + 筛选 按钮 */}
          <Popover
            content={filterPopoverContent}
            trigger="click"
            open={filterPopoverOpen}
            onOpenChange={(open) => {
              setFilterPopoverOpen(open)
              if (!open) setPendingFilterField(null)
            }}
            placement="bottomLeft"
            overlayStyle={{ borderRadius: 12 }}
          >
            <button
              type="button"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'pointer',
                background: 'transparent',
                border: '1px dashed #c8c4be',
                borderRadius: 20,
                padding: '4px 12px',
                fontSize: 13,
                color: '#5645d4',
                fontWeight: 500,
                fontFamily: 'inherit',
                whiteSpace: 'nowrap',
                flexShrink: 0,
                transition: 'border-color 0.15s, background 0.15s',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = '#5645d4'
                ;(e.currentTarget as HTMLButtonElement).style.background = '#f8f6ff'
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = '#c8c4be'
                ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
              }}
            >
              <FilterOutlined style={{ fontSize: 12 }} />
              筛选
            </button>
          </Popover>

          {/* 活跃筛选时显示"清除" */}
          {activeFilters.length > 0 && (
            <button
              type="button"
              onClick={clearAllFilters}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'pointer',
                background: 'transparent',
                border: 'none',
                padding: '4px 8px',
                fontSize: 12,
                color: '#e03131',
                fontWeight: 500,
                fontFamily: 'inherit',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              <CloseCircleOutlined style={{ fontSize: 11 }} />
              清除全部
            </button>
          )}
        </div>

        {/* 新建按钮（固定在右侧） */}
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setDrawerOpen(true)}
          style={{ flexShrink: 0 }}
        >
          新建辨识
        </Button>
        <Button
          icon={<ClusterOutlined />}
          onClick={() => setBatchDrawerOpen(true)}
          style={{ flexShrink: 0 }}
        >
          批量辨识
        </Button>
      </div>

      {/* ── 内容卡片 ── */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #e5e3df',
          padding: '16px 20px',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* ── 批量删除栏 ── */}
        {selectedRowKeys.length > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 16px',
              marginBottom: 12,
              borderRadius: 8,
              background: '#fff1f0',
              border: '1px solid #ffccc7',
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 13, color: '#e03131', fontWeight: 500 }}>
              已选择 {selectedRowKeys.length} 条记录
            </span>
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={deleting}
              onClick={handleBatchDelete}
              size="small"
            >
              删除
            </Button>
          </div>
        )}

        {/* ── 全局样式 ── */}
        <style>{`
          .hi-workflow-table .ant-table-row {
            transition: background 0.12s ease;
          }
          .hi-workflow-table thead th {
            text-align: center !important;
          }
          .hi-workflow-table .ant-table-cell {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
        `}</style>

        {/* ── 表格 ── */}
        <Table
          className="hi-workflow-table"
          columns={columns}
          dataSource={data}
          rowKey="id"
          size="small"
          loading={loading}
          scroll={{ x: 'max-content' }}
          onRow={(record) => ({
            onMouseEnter: () => setHoveredRowId(record.id),
            onMouseLeave: () => setHoveredRowId((prev) => (prev === record.id ? null : prev)),
          })}
          pagination={{
            current: queryParams.page,
            pageSize: queryParams.page_size,
            total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => setQueryParams({ page, page_size: pageSize }),
          }}
        />
      </div>

      {/* ── 批次进度面板 ── */}
      {activeBatchId && (
        <div style={{ marginBottom: 16 }}>
          <BatchProgressPanel batchId={activeBatchId} />
        </div>
      )}

      {/* ── 新建辨识抽屉 ── */}
      <HazardIdentificationDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onDone={() => {
          setDrawerOpen(false)
          loadData()
          loadStats()
        }}
      />

      {/* ── 批量辨识抽屉 ── */}
      <HazardIdentificationBatchDrawer
        open={batchDrawerOpen}
        onClose={() => setBatchDrawerOpen(false)}
        onDone={() => {
          setBatchDrawerOpen(false)
          loadData()
          loadStats()
        }}
      />
    </div>
  )
}
