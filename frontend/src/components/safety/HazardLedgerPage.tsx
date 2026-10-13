'use client'

import { useState, useMemo, useCallback, useRef } from 'react'
import {
  Table,
  Button,
  Input,
  Space,
  Popover,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  CloseCircleOutlined,
  FilterOutlined,
  CaretUpFilled,
  CaretDownFilled,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { fetchHazards, fetchHazardStats } from '@/lib/api/safety/hazard'
import type {
  HazardReport,
} from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  normalizeHazardLevel,
  HAZARD_CATEGORY_OPTIONS,
  SUPERVISION_LEVEL_OPTIONS,
  SUPERVISION_PROGRESS_NOT_UPDATED,
  VERIFY_LEVEL_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import { CircleCheck, FileWarning, TimerOff, Wrench } from 'lucide-react'


// ── 整改状态语义 tone（StatusTag）──
const RECTIFICATION_STATUS_CONFIG: Record<string, { label: string; tone: Tone }> = {
  pending:          { label: '待整改', tone: 'warn' },
  in_progress:      { label: '整改中', tone: 'info' },
  replied:          { label: '待复核', tone: 'warn' },
  level1_approved:  { label: '复核中', tone: 'info' },
  level2_approved:  { label: '复核中', tone: 'info' },
  rejected:         { label: '已驳回', tone: 'danger' },
  closed:           { label: '已关闭', tone: 'ok' },
}

// ── 隐患等级语义 tone（一般=蓝/较大=橙/重大=红）──
const LEVEL_TONE: Record<string, Tone> = {
  general: 'info',
  serious: 'warn',
  major:   'danger',
}

// ── 督办等级语义 tone（红色预警=红/一般预警=橙/已关闭=绿）──
const SUPERVISION_TONE: Record<string, Tone> = {
  '红色预警': 'danger',
  '一般预警': 'warn',
  'closed': 'ok',
}

// ── 统计卡配置（点击卡片 = 按整改状态快捷筛选，沿用统计药丸交互；逾期仅展示） ──
const STATS_CARDS: Array<{ key: string; label: string; tone: Tone; filterable: boolean }> = [
  { key: '',            label: '全部',   tone: 'default', filterable: true  },
  { key: 'pending',     label: '待整改', tone: 'warn',    filterable: true  },
  { key: 'in_progress', label: '整改中', tone: 'info',    filterable: true  },
  { key: 'replied',     label: '待复核', tone: 'warn',    filterable: true  },
  { key: 'rejected',    label: '已驳回', tone: 'danger',  filterable: true  },
  { key: 'closed',      label: '已关闭', tone: 'ok',      filterable: true  },
  { key: 'overdue',     label: '逾期',   tone: 'expired', filterable: false },
]

// ── 可筛选字段配置（用于多维筛选弹出菜单）──
interface FilterFieldConfig {
  key: string
  label: string
  type?: 'text' | 'select'
  options: Array<{ value: string; label: string }>
}
const FILTER_FIELDS: FilterFieldConfig[] = [
  {
    key: 'hazard_level',
    label: '隐患等级',
    options: HAZARD_LEVEL_OPTIONS,
  },
  {
    key: 'supervision_level',
    label: '督办等级',
    options: SUPERVISION_LEVEL_OPTIONS,
  },
  {
    key: 'hazard_type',
    label: '隐患类型',
    options: HAZARD_TYPE_OPTIONS,
  },
  {
    key: 'hazard_category',
    label: '隐患类别',
    options: HAZARD_CATEGORY_OPTIONS,
  },
  {
    key: 'inspection_category',
    label: '检查类别',
    options: [
      { value: '日常检查', label: '日常检查' },
      { value: '专项检查', label: '专项检查' },
      { value: '月度安全检查', label: '月度安全检查' },
      { value: '周检', label: '周检' },
      { value: '节假日检查', label: '节假日检查' },
      { value: '季节性检查', label: '季节性检查' },
    ],
  },
  {
    key: 'department',
    label: '责任部门',
    type: 'text' as const,
    options: [],
  },
]

// ── 隐患类别标签映射 ──
const HAZARD_CATEGORY_LABEL_MAP: Record<string, string> = {}
HAZARD_CATEGORY_OPTIONS.forEach((o) => { HAZARD_CATEGORY_LABEL_MAP[o.value] = o.label })

export default function HazardLedgerPage() {
  const [searchText, setSearchText] = useState('')
  const [searchApplied, setSearchApplied] = useState(false)
  const [submittedKeyword, setSubmittedKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [levelFilter, setLevelFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [inspectionCategoryFilter, setInspectionCategoryFilter] = useState<string | undefined>()
  const [deptFilter, setDeptFilter] = useState<string | undefined>()

  // ── 排序状态 ──
  const [sortField, setSortField] = useState<string | undefined>()
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend' | undefined>()

  // ── 筛选弹出框状态 ──
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [pendingFilterField, setPendingFilterField] = useState<string | null>(null)

  // ── 筛选栏滚动容器 ref ──
  const filterScrollRef = useRef<HTMLDivElement>(null)

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 全局统计 query
  const statsQuery = useQuery({
    queryKey: ['hazard-stats'],
    queryFn: fetchHazardStats,
  })
  const hazardStats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['hazards', {
      page, pageSize,
      statusFilter, typeFilter, levelFilter, categoryFilter, inspectionCategoryFilter, deptFilter,
      submittedKeyword,
    }],
    queryFn: () => fetchHazards({
      page, page_size: pageSize,
      rectification_status: statusFilter,
      hazard_type: typeFilter,
      hazard_level: levelFilter,
      hazard_category: categoryFilter,
      inspection_category: inspectionCategoryFilter,
      department: deptFilter,
      keyword: submittedKeyword || undefined,
    }),
  })

  // 客户端排序
  const hazards = useMemo(() => {
    const items = listData?.items ?? []
    if (sortField && sortOrder) {
      return [...items].sort((a, b) => {
        const aVal = (a as unknown as Record<string, unknown>)[sortField] ?? ''
        const bVal = (b as unknown as Record<string, unknown>)[sortField] ?? ''
        const cmp = String(aVal).localeCompare(String(bVal), 'zh-CN')
        return sortOrder === 'ascend' ? cmp : -cmp
      })
    }
    return items
  }, [listData?.items, sortField, sortOrder])

  const hazardTotal = listData?.total ?? 0

  // ── 活跃筛选条件 (多维表格 chip 模式) ──
  const activeFilters = useMemo(() => {
    const list: { key: string; fieldLabel: string; value: string; valueLabel: string }[] = []
    if (levelFilter) {
      const opt = HAZARD_LEVEL_OPTIONS.find((o) => o.value === levelFilter)
      list.push({ key: 'hazard_level', fieldLabel: '等级', value: levelFilter, valueLabel: opt?.label || levelFilter })
    }
    if (typeFilter) {
      const opt = HAZARD_TYPE_OPTIONS.find((o) => o.value === typeFilter)
      list.push({ key: 'hazard_type', fieldLabel: '类型', value: typeFilter, valueLabel: opt?.label || typeFilter })
    }
    if (categoryFilter) {
      const opt = HAZARD_CATEGORY_OPTIONS.find((o) => o.value === categoryFilter)
      list.push({ key: 'hazard_category', fieldLabel: '类别', value: categoryFilter, valueLabel: opt?.label || categoryFilter })
    }
    if (inspectionCategoryFilter) {
      const opt = FILTER_FIELDS.find((f) => f.key === 'inspection_category')?.options.find((o) => o.value === inspectionCategoryFilter)
      list.push({ key: 'inspection_category', fieldLabel: '检查类别', value: inspectionCategoryFilter, valueLabel: opt?.label || inspectionCategoryFilter })
    }
    if (deptFilter) {
      list.push({ key: 'department', fieldLabel: '责任部门', value: deptFilter, valueLabel: deptFilter })
    }
    return list
  }, [levelFilter, typeFilter, categoryFilter, inspectionCategoryFilter, deptFilter])

  // 移除单个筛选条件
  const removeFilter = useCallback((key: string) => {
    setPage(1)
    switch (key) {
      case 'hazard_level': setLevelFilter(undefined); break
      case 'hazard_type': setTypeFilter(undefined); break
      case 'hazard_category': setCategoryFilter(undefined); break
      case 'inspection_category': setInspectionCategoryFilter(undefined); break
      case 'department': setDeptFilter(undefined); break
    }
  }, [setPage])

  // 清除所有筛选
  const clearAllFilters = useCallback(() => {
    setLevelFilter(undefined)
    setTypeFilter(undefined)
    setCategoryFilter(undefined)
    setInspectionCategoryFilter(undefined)
    setDeptFilter(undefined)
    setStatusFilter(undefined)
    setSearchText('')
    setSearchApplied(false)
    setPage(1)
  }, [setPage])

  // 处理筛选字段选择
  const handleFilterFieldSelect = (fieldKey: string) => {
    setPendingFilterField(fieldKey)
    // 关闭字段选择面板，打开值选择面板
  }

  const handleFilterValueSelect = (fieldKey: string, value: string) => {
    setPage(1)
    switch (fieldKey) {
      case 'hazard_level': setLevelFilter(value); break
      case 'hazard_type': setTypeFilter(value); break
      case 'hazard_category': setCategoryFilter(value); break
      case 'inspection_category': setInspectionCategoryFilter(value); break
      case 'department': setDeptFilter(value); break
    }
    setPendingFilterField(null)
    setFilterPopoverOpen(false)
  }

  const handleSearch = () => {
    setSubmittedKeyword(searchText)
    setSearchApplied(true)
    setPage(1)
  }

  const handleSearchBack = () => {
    setSubmittedKeyword('')
    setSearchText('')
    setSearchApplied(false)
    setPage(1)
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

  const getLevelLabel = (level: string) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === normalizeHazardLevel(level))
    return option?.label || level
  }

  // ── 统计（来自 API 全局数据，不受分页/筛选影响）──
  const getPillCount = (key: string): number => {
    if (!hazardStats) return 0
    switch (key) {
      case '': return hazardStats.total
      case 'pending_review': return hazardStats.pending_review
      case 'pending': return hazardStats.pending
      case 'in_progress': return hazardStats.in_progress
      case 'replied': return hazardStats.replied
      case 'verifying': return hazardStats.verifying
      case 'rejected': return hazardStats.rejected
      case 'closed': return hazardStats.closed
      case 'overdue': return hazardStats.overdue
      default: return 0
    }
  }

  const handlePillClick = (pill: { key: string; filterable: boolean }) => {
    if (!pill.filterable) return
    if (pill.key === '') {
      setStatusFilter(undefined)
    } else {
      setStatusFilter(statusFilter === pill.key ? undefined : pill.key)
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

  // ── 表格列定义 ──
  const columns: ColumnsType<HazardReport> = [
    {
      title: '隐患编号',
      dataIndex: 'hazard_no',
      key: 'hazard_no',
      width: 140,
      sorter: false,
      render: (text: string) => (
        <span style={{ fontWeight: 600, fontSize: 13 }}>{text}</span>
      ),
    },
    {
      title: '检查类别',
      dataIndex: 'inspection_category',
      key: 'inspection_category',
      width: 110,
      render: (text: string) => {
        if (!text) return <span style={{ color: '#a4a097' }}>-</span>
        // Bitable 多选用逗号分隔，取第一项展示
        const first = text.split(/[,，]/)[0]?.trim()
        return <span style={{ fontSize: 13 }}>{first}{text.includes(',') || text.includes('，') ? '…' : ''}</span>
      },
    },
    {
      title: (
        <span
          onClick={() => handleSort('hazard_level')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          隐患等级{renderSortIcon('hazard_level')}
        </span>
      ),
      dataIndex: 'hazard_level',
      key: 'hazard_level',
      width: 100,
      sorter: false,
      render: (_: unknown, record: HazardReport) => {
        // 督办判定以人工等级为准，台账展示优先显示人工等级，缺失时回退 AI 等级
        // 归一化兼容 DB 中英文混存（一般隐患/general）
        const level = normalizeHazardLevel(record.hazard_level_manual || record.hazard_level)
        return <StatusTag tone={LEVEL_TONE[level] ?? 'default'} label={getLevelLabel(level)} />
      },
    },
    {
      title: '督办等级',
      dataIndex: 'supervision_level',
      key: 'supervision_level',
      width: 95,
      render: (level: string) => {
        const opt = SUPERVISION_LEVEL_OPTIONS.find((o) => o.value === level)
        if (!opt) return <StatusTag label={level || '-'} />
        return <StatusTag tone={SUPERVISION_TONE[level] ?? 'default'} label={opt.label} />
      },
    },
    {
      title: '进展状态',
      dataIndex: 'supervision_progress_status',
      key: 'supervision_progress_status',
      width: 100,
      render: (_: unknown, record: HazardReport) => {
        if (record.supervision_progress_status === SUPERVISION_PROGRESS_NOT_UPDATED) {
          return <StatusTag tone="danger" label={SUPERVISION_PROGRESS_NOT_UPDATED} />
        }
        return <span style={{ color: '#a4a097' }}>-</span>
      },
    },
    {
      title: (
        <span
          onClick={() => handleSort('hazard_category')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          隐患类别{renderSortIcon('hazard_category')}
        </span>
      ),
      dataIndex: 'hazard_category',
      key: 'hazard_category',
      width: 100,
      sorter: false,
      render: (category: string) => {
        const option = HAZARD_CATEGORY_OPTIONS.find((o) => o.value === category)
        return <StatusTag label={option?.label || category || '-'} />
      },
    },
    {
      title: (
        <span
          onClick={() => handleSort('hazard_type')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          隐患类型{renderSortIcon('hazard_type')}
        </span>
      ),
      dataIndex: 'hazard_type',
      key: 'hazard_type',
      width: 120,
      sorter: false,
      render: (type: string) => {
        const option = HAZARD_TYPE_OPTIONS.find((o) => o.value === type)
        return <StatusTag label={option?.label || type} />
      },
    },
    {
      title: '隐患描述',
      dataIndex: 'description',
      key: 'description',
      width: 150,
      ellipsis: true,
    },
    {
      title: (
        <span
          onClick={() => handleSort('department')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          责任部门{renderSortIcon('department')}
        </span>
      ),
      dataIndex: 'department',
      key: 'department',
      width: 100,
      sorter: false,
    },
    {
      title: '检查人员',
      dataIndex: 'discovered_by_name',
      key: 'discovered_by_name',
      width: 90,
      ellipsis: true,
      render: (text: string) => text || <span style={{ color: '#a4a097' }}>-</span>,
    },
    {
      title: (
        <span
          onClick={() => handleSort('discovered_at')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          检查日期{renderSortIcon('discovered_at')}
        </span>
      ),
      dataIndex: 'discovered_at',
      key: 'discovered_at',
      width: 100,
      sorter: false,
      render: (date: string) => {
        if (!date) return <span style={{ color: '#a4a097' }}>-</span>
        return <span style={{ fontSize: 13 }}>{dayjs(date).format('YYYY-MM-DD')}</span>
      },
    },
    {
      title: '整改状态',
      dataIndex: 'rectification_status',
      key: 'rectification_status',
      width: 80,
      render: (status: string) => {
        const cfg = RECTIFICATION_STATUS_CONFIG[status]
        if (!cfg) return <StatusTag label={status} />
        return <StatusTag tone={cfg.tone} label={cfg.label} />
      },
    },
    {
      title: '复核进度',
      key: 'verify_progress',
      width: 100,
      render: (_: unknown, record: HazardReport) => {
        const levels = [
          { status: record.verify_level_1_status || 'pending', label: '一' },
          { status: record.verify_level_2_status || 'pending', label: '二' },
          { status: record.verify_level_3_status || 'pending', label: '三' },
        ]
        return (
          <Space size={4}>
            {levels.map((lv) => {
              const opt = VERIFY_LEVEL_STATUS_OPTIONS.find((o) => o.value === lv.status)
              const color = opt?.color || '#c8c4be'
              const bg = lv.status === 'approved'
                ? '#d9f3e1'
                : lv.status === 'rejected'
                  ? '#fde0ec'
                  : lv.status === 'no_review_needed'
                    ? '#e8e6e1'
                    : '#f0eeec'
              return (
                <span
                  key={lv.label}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 22,
                    height: 22,
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 600,
                    color,
                    background: bg,
                  }}
                >
                  {lv.label}
                </span>
              )
            })}
          </Space>
        )
      },
    },
    {
      title: (
        <span
          onClick={() => handleSort('deadline')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          整改期限{renderSortIcon('deadline')}
        </span>
      ),
      dataIndex: 'deadline',
      key: 'deadline',
      width: 100,
      sorter: false,
      render: (date: string) => {
        if (!date) return '-'
        const isOverdue = dayjs(date).isBefore(dayjs())
        return (
          <span style={{ color: isOverdue ? '#e03131' : '#1a1a1a', fontWeight: isOverdue ? 600 : 400, fontSize: 13 }}>
            {dayjs(date).format('YYYY-MM-DD')}
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
              placeholder="请输入责任部门名称"
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
    <div>
      {/* ── 页头 ── */}
      <PageHeader
        breadcrumb={['安全管理', '隐患排查与治理']}
        title="隐患排查与治理"
        description="隐患全生命周期台账：排查、整改、复核进展与趋势"
      />

      {/* ── 全生命周期统计行（全局口径，点击卡片 = 按整改状态快捷筛选） ── */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {STATS_CARDS.map((card) => {
          const isActive = card.key === ''
            ? statusFilter === undefined
            : card.filterable && statusFilter === card.key
          const count = getPillCount(card.key)
          return (
            <StatCard
              key={card.key || 'all'}
              label={card.label}
              value={count}
              tone={card.key === '' || count > 0 ? card.tone : 'default'}
              loading={statsQuery.isLoading}
              sub={
                !card.filterable
                  ? '超期未关闭'
                  : isActive
                    ? '筛选中 · 点击取消'
                    : '点击按状态筛选'
              }
              icon={
                card.key === ''
                  ? <FileWarning size={16} />
                  : card.key === 'pending'
                    ? <Wrench size={16} />
                    : card.key === 'closed'
                      ? <CircleCheck size={16} />
                      : card.key === 'overdue'
                        ? <TimerOff size={16} />
                        : undefined
              }
              onClick={card.filterable ? () => handlePillClick(card) : undefined}
            />
          )
        })}
      </div>

      {/* ── 多维筛选栏（横向滚动）── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 16,
          minHeight: 32,
        }}
      >
        {/* 搜索框（固定在左侧）+ 确认/返回按钮 */}
        <div style={{ display: 'flex', alignItems: 'stretch', flexShrink: 0 }}>
          <Input
            placeholder="搜索隐患编号/描述"
            prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
            style={{
              width: 220,
              height: 40,
              borderTopRightRadius: 0,
              borderBottomRightRadius: 0,
              borderRight: 'none',
            }}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value)
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
              disabled={!searchText.trim()}
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

      </div>

      {/* ── 台账明细 ── */}
      <SectionCard
        title="隐患台账"
        description={`台账只读监控 · 业务操作在飞书多维表格与机器人（当前筛选共 ${hazardTotal} 条）`}
      >
        {/* ── 全局样式：行悬停效果 + 隐藏式复选框 ── */}
        <style>{`
          .hazard-ledger-table .ant-table-row {
            transition: background 0.12s ease;
          }
          .hazard-ledger-table thead th {
            text-align: center !important;
          }
          .hazard-ledger-table .ant-table-cell {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
        `}</style>

        {/* ── 表格 ── */}
        <Table
          className="hazard-ledger-table"
          columns={columns}
          dataSource={hazards}
          rowKey="id"
          size="small"
          loading={isLoading}
          scroll={{ x: 'max-content' }}
          locale={{
            emptyText: (
              <EmptyGuide
                compact
                title="暂无符合条件的隐患记录"
                description="调整搜索或筛选条件后重试"
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: hazardTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage)
              setPageSize(nextPageSize)
            },
          }}
        />
      </SectionCard>

    </div>
  )
}
