'use client'

import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  Input,
  Button,
  Space,
  Tag,
  App,
  Typography,
  Modal,
  Descriptions,
  Spin,
  DatePicker,
  Checkbox,
  Popover,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  ExportOutlined,
  DownloadOutlined,
  FilterOutlined,
  CloseCircleOutlined,
  CaretUpFilled,
  CaretDownFilled,
  DeleteOutlined,
} from '@ant-design/icons'
import {
  getHazardIdentifications,
  getHILedgerStats,
  exportHazardLedgerPdf,
  deleteHazardIdentification,
} from '@/actions/safety'
import type { HazardIdentification, HazardLedgerStats } from '@/types/safety'
import { RISK_LEVEL_OPTIONS } from '@/types/safety'
import dayjs from 'dayjs'
import { statusPill } from '@/components/safety/shared-styles'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── 风险等级语义色（表格内 pills）──
const LEVEL_CONFIG: Record<string, { color: string; bg: string }> = {
  level_1: { color: '#e03131', bg: '#fde0ec' },
  level_2: { color: '#dd5b00', bg: '#ffe8d4' },
  level_3: { color: '#0075de', bg: '#dcecfa' },
  level_4: { color: '#1aae39', bg: '#d9f3e1' },
}

// ── 统计药丸配置 ──
const STATS_PILLS = [
  { key: '',        label: '全部',     dotColor: '#1a1a1a' },
  { key: 'level_1', label: '重大风险', dotColor: '#e03131' },
  { key: 'level_2', label: '较大风险', dotColor: '#dd5b00' },
  { key: 'level_3', label: '一般风险', dotColor: '#0075de' },
  { key: 'level_4', label: '低风险',   dotColor: '#1aae39' },
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
    key: 'risk_level',
    label: '风险等级',
    options: RISK_LEVEL_OPTIONS,
  },
  {
    key: 'department',
    label: '部门',
    type: 'text' as const,
    options: [],
  },
  {
    key: 'position',
    label: '岗位',
    type: 'text' as const,
    options: [],
  },
]

// ── 危险源辨识特有字段标签 ──
const HI_FIELD_LABELS: Record<string, string> = {
  hazard_id_no: '编号',
  department: '部门',
  position: '岗位',
  production_step: '生产步骤',
  specific_activity: '作业活动',
  equipment_facilities: '设备设施',
  raw_auxiliary_materials: '原辅料',
  operation_frequency: '作业频次',
  hazard_type: '危险类型',
  possible_accident: '可能事故',
  unsafe_behavior: '不规范行为',
  inherent_risk_level: '固有风险等级',
  residual_risk_level: '残余风险等级',
  post_risk_level: '措施后风险等级',
  control_level: '管控层级',
  responsible_person: '责任人',
  recommendation_type: '建议措施类型',
  recommendation_priority: '建议措施优先级',
}

export default function HazardLedgerPanel() {
  const router = useRouter()
  const { message: msgApi } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<HazardIdentification[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<HazardLedgerStats>({
    total: 0, level_1: 0, level_2: 0, level_3: 0, level_4: 0,
  })
  const [queryParams, setQueryParams] = useState({ page: 1, page_size: 20 })
  const [keyword, setKeyword] = useState('')
  const [searchApplied, setSearchApplied] = useState(false)
  const searchKeywordRef = useRef('')
  const [riskLevel, setRiskLevel] = useState<string | undefined>()
  const [department, setDepartment] = useState<string | undefined>()
  const [position, setPosition] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)

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

  // ── AI 导出 Modal 状态 ──
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [naturalQuery, setNaturalQuery] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportStep, setExportStep] = useState<string>('')

  // ── 展开行 key ──
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([])

  // ── 筛选栏滚动容器 ref ──
  const filterScrollRef = useRef<HTMLDivElement>(null)

  // ── 活跃筛选条件 ──
  const activeFilters = useMemo(() => {
    const list: { key: string; fieldLabel: string; value: string; valueLabel: string }[] = []
    if (riskLevel) {
      const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === riskLevel)
      list.push({ key: 'risk_level', fieldLabel: '等级', value: riskLevel, valueLabel: opt?.label || riskLevel })
    }
    if (department) {
      list.push({ key: 'department', fieldLabel: '部门', value: department, valueLabel: department })
    }
    if (position) {
      list.push({ key: 'position', fieldLabel: '岗位', value: position, valueLabel: position })
    }
    return list
  }, [riskLevel, department, position])

  // 移除单个筛选条件
  const removeFilter = useCallback((key: string) => {
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    switch (key) {
      case 'risk_level': setRiskLevel(undefined); break
      case 'department': setDepartment(undefined); break
      case 'position': setPosition(undefined); break
    }
  }, [queryParams.page_size, setQueryParams])

  // 清除所有筛选
  const clearAllFilters = useCallback(() => {
    setRiskLevel(undefined)
    setDepartment(undefined)
    setPosition(undefined)
    setKeyword('')
    setSearchApplied(false)
    setDateRange(null)
    setQueryParams({ page: 1, page_size: 20 })
  }, [setQueryParams])

  // 处理筛选字段选择
  const handleFilterFieldSelect = (fieldKey: string) => {
    setPendingFilterField(fieldKey)
  }

  const handleFilterValueSelect = (fieldKey: string, value: string) => {
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    switch (fieldKey) {
      case 'risk_level': setRiskLevel(value); break
      case 'department': setDepartment(value); break
      case 'position': setPosition(value); break
    }
    setPendingFilterField(null)
    setFilterPopoverOpen(false)
  }

  const loadStats = async () => {
    try {
      const res = await getHILedgerStats({
        department,
        position,
        risk_level: riskLevel,
        date_from: dateRange?.[0],
        date_to: dateRange?.[1],
      })
      if (res.code === 200 && res.data) {
        setStats(res.data as HazardLedgerStats)
      }
    } catch { /* non-critical */ }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await getHazardIdentifications({
        ...queryParams,
        overall_status: 'completed',
        keyword: searchKeywordRef.current || undefined,
        department,
        position,
        risk_level: riskLevel,
        date_from: dateRange?.[0],
        date_to: dateRange?.[1],
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
      msgApi.error('加载台账失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadStats() }, [])

  useEffect(() => {
    setSelectedRowKeys([])
    loadData()
  }, [queryParams.page, queryParams.page_size, riskLevel, department, position])

  // 排序/日期变化时重新加载
  useEffect(() => {
    if (sortField) loadData()
  }, [sortField, sortOrder])

  useEffect(() => {
    loadData()
    loadStats()
  }, [dateRange])

  const handleSearch = () => {
    searchKeywordRef.current = keyword
    setSearchApplied(true)
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    loadData()
    loadStats()
  }

  const handleSearchBack = () => {
    searchKeywordRef.current = ''
    setKeyword('')
    setSearchApplied(false)
    loadData()
    loadStats()
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

  // ── base64 → Blob → 触发下载 ──
  const downloadBase64 = (base64: string, filename: string, mimeType: string) => {
    const byteCharacters = atob(base64)
    const byteNumbers = new Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i)
    }
    const byteArray = new Uint8Array(byteNumbers)
    const blob = new Blob([byteArray], { type: mimeType })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  }

  // ── 导出 PDF ──
  const handleExportPdf = async () => {
    setExporting(true)
    setExportStep('AI 正在解析筛选条件…')
    try {
      const result = await exportHazardLedgerPdf({
        natural_query: naturalQuery.trim() || undefined,
      })
      setExportStep('下载中…')
      downloadBase64(
        result.data || '',
        `危险源辨识台账_${new Date().toISOString().slice(0, 10)}.pdf`,
        'application/pdf'
      )
      msgApi.success('PDF 导出成功')
      setExportModalOpen(false)
    } catch {
      msgApi.error('PDF 导出失败')
    } finally {
      setExporting(false)
      setExportStep('')
    }
  }

  const handleCloseExportModal = () => {
    setExportModalOpen(false)
    setNaturalQuery('')
  }

  // ── 统计药丸计数 ──
  const getPillCount = (key: string): number => {
    switch (key) {
      case '': return stats.total
      case 'level_1': return stats.level_1
      case 'level_2': return stats.level_2
      case 'level_3': return stats.level_3
      case 'level_4': return stats.level_4
      default: return 0
    }
  }

  const handlePillClick = (pill: typeof STATS_PILLS[number]) => {
    if (pill.key === '') {
      setRiskLevel(undefined)
    } else {
      setRiskLevel(riskLevel === pill.key ? undefined : pill.key)
    }
    setQueryParams({ page: 1, page_size: queryParams.page_size })
  }

  const getRiskTag = (level?: string, label?: string) => {
    if (!level) return '-'
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <Tag color={opt?.color}>{label || level}</Tag>
  }

  const getRiskPill = (level?: string, label?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    const cfg = LEVEL_CONFIG[level]
    if (!cfg) return <Tag>{label || level}</Tag>
    return <span style={statusPill(cfg.color, cfg.bg)}>{label || level}</span>
  }

  const getControlLevelTag = (level?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    const colorMap: Record<string, string> = {
      '公司级': 'red',
      '部门级': 'orange',
      '班组级': 'blue',
    }
    return <Tag color={colorMap[level] || 'default'}>{level}</Tag>
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
          return <Checkbox checked onChange={handleToggle} style={{ zIndex: 2 }} />
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
      render: (text: string) => text || <span style={{ color: '#a4a097' }}>-</span>,
    },
    {
      title: '生产步骤',
      dataIndex: 'production_step',
      key: 'production_step',
      width: 140,
      ellipsis: true,
      render: (text: string) => {
        if (!text) return <span style={{ color: '#a4a097' }}>-</span>
        return <span style={{ fontSize: 13 }}>{text}</span>
      },
    },
    {
      title: '作业活动',
      dataIndex: 'specific_activity',
      key: 'specific_activity',
      width: 140,
      ellipsis: true,
      render: (v?: string) => v || <span style={{ color: '#a4a097' }}>-</span>,
    },
    {
      title: '事故类型',
      dataIndex: 'possible_accident',
      key: 'possible_accident',
      width: 100,
      ellipsis: true,
      render: (v?: string) => v || <span style={{ color: '#a4a097' }}>-</span>,
    },
    {
      title: (
        <span
          onClick={() => handleSort('inherent_risk_level')}
          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          固有风险{renderSortIcon('inherent_risk_level')}
        </span>
      ),
      key: 'inherent_risk',
      width: 90,
      sorter: false,
      render: (_, r) => getRiskPill(r.inherent_risk_level, r.inherent_risk_label),
    },
    {
      title: '残余风险',
      key: 'residual_risk',
      width: 90,
      render: (_, r) => getRiskPill(r.residual_risk_level, r.residual_risk_label),
    },
    {
      title: '措施后风险',
      key: 'post_risk',
      width: 90,
      render: (_, r) => getRiskPill(r.post_risk_level, r.post_risk_label),
    },
    {
      title: '管控层级',
      dataIndex: 'control_level',
      key: 'control_level',
      width: 80,
      render: (v?: string) => getControlLevelTag(v),
    },
    {
      title: '责任人',
      dataIndex: 'responsible_person',
      key: 'responsible_person',
      width: 80,
      ellipsis: true,
      render: (text: string) => text || <span style={{ color: '#a4a097' }}>-</span>,
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
      width: 110,
      sorter: false,
      render: (v: string) => {
        if (!v) return <span style={{ color: '#a4a097' }}>-</span>
        return <span style={{ fontSize: 13 }}>{dayjs(v).format('YYYY-MM-DD')}</span>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      align: 'center',
      render: (_, r) => (
        <Button
          type="link" size="small"
          onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
          style={{ color: '#0075de', fontWeight: 600 }}
        >
          查看
        </Button>
      ),
    },
  ]

  // ── 展开行渲染 ──
  const expandedRowRender = (record: HazardIdentification) => {
    const lecRow = (label: string, l?: number, e?: number, c?: number, d?: number, level?: string, levelLabel?: string) => (
      <Descriptions
        size="small"
        column={6}
        colon={false}
        title={<Text strong style={{ fontSize: 13 }}>{label}</Text>}
        style={{ marginBottom: 0 }}
      >
        <Descriptions.Item label="L">{l ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="E">{e ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="C">{c ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="D">{d ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="等级" span={2}>
          {level ? getRiskTag(level, levelLabel) : '-'}
        </Descriptions.Item>
      </Descriptions>
    )

    return (
      <div style={{ padding: '12px 24px', background: '#fafafa', borderRadius: 8 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {lecRow('固有风险评价', record.l_inherent, record.e_inherent, record.c_inherent, record.d_inherent, record.inherent_risk_level, record.inherent_risk_label)}

          {(record.existing_engineering_controls || record.existing_management_controls || record.existing_ppe || record.existing_emergency_measures) && (
            <Descriptions size="small" column={2} colon={false} title={<Text strong style={{ fontSize: 13 }}>现有控制措施</Text>}>
              {record.existing_engineering_controls && (
                <Descriptions.Item label="工程控制">{record.existing_engineering_controls}</Descriptions.Item>
              )}
              {record.existing_management_controls && (
                <Descriptions.Item label="管理措施">{record.existing_management_controls}</Descriptions.Item>
              )}
              {record.existing_ppe && (
                <Descriptions.Item label="PPE">{record.existing_ppe}</Descriptions.Item>
              )}
              {record.existing_emergency_measures && (
                <Descriptions.Item label="应急措施">{record.existing_emergency_measures}</Descriptions.Item>
              )}
            </Descriptions>
          )}

          {lecRow('残余风险评价', record.l_residual, record.e_residual, record.c_residual, record.d_residual, record.residual_risk_level, record.residual_risk_label)}

          {record.recommendation_content && (
            <Descriptions size="small" column={2} colon={false} title={<Text strong style={{ fontSize: 13 }}>建议措施</Text>}>
              {record.recommendation_type && (
                <Descriptions.Item label="类型">{record.recommendation_type}</Descriptions.Item>
              )}
              {record.recommendation_priority && (
                <Descriptions.Item label="优先级">
                  <Tag>{record.recommendation_priority}</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="内容" span={2}>{record.recommendation_content}</Descriptions.Item>
            </Descriptions>
          )}

          {lecRow('措施后风险评价', record.l_post, record.e_post, record.c_post, record.d_post, record.post_risk_level, record.post_risk_label)}
        </Space>
      </div>
    )
  }

  // ── 筛选弹出内容（对齐隐患台账模式）──
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
              placeholder={
                pendingFilterField === 'department' ? '请输入部门名称' :
                pendingFilterField === 'position' ? '请输入岗位名称' :
                '请输入'
              }
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
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        marginBottom: 24,
      }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', margin: 0, marginBottom: 4, lineHeight: 1.3 }}>
            危险源辨识台账
          </h2>
          <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
            已完成危险源辨识记录的查询、统计与导出
          </p>
        </div>
        <Button type="primary" icon={<ExportOutlined />} onClick={() => setExportModalOpen(true)}>
          导出 PDF
        </Button>
      </div>

      {/* ── 统计药丸 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {STATS_PILLS.map((pill) => {
          const pillKey = pill.key || 'all'
          const isActive = pill.key === ''
            ? riskLevel === undefined
            : riskLevel === pill.key
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
                cursor: 'pointer',
                background: isActive ? '#f0eeec' : 'transparent',
                border: isActive ? '1px solid #c8c4be' : '1px solid transparent',
                borderRadius: 20,
                padding: '4px 12px',
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? '#1a1a1a' : '#5d5b54',
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
                }}
              />
              {pill.label}
              <span style={{ fontWeight: 600, color: pill.dotColor, marginLeft: 2 }}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* ── 多维筛选栏（对齐隐患台账）── */}
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
            placeholder="搜索编号/部门/岗位/作业"
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

        {/* 日期范围选择器 */}
        <RangePicker
          placeholder={['开始日期', '结束日期']}
          value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')])
            } else {
              setDateRange(null)
            }
          }}
          style={{ height: 40, flexShrink: 0 }}
        />

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
          .hi-ledger-table .ant-table-row {
            transition: background 0.12s ease;
          }
          .hi-ledger-table thead th {
            text-align: center !important;
          }
          .hi-ledger-table .ant-table-cell {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
        `}</style>

        {/* ── 表格 ── */}
        <Table
          className="hi-ledger-table"
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 'max-content' }}
          size="small"
          onRow={(record) => ({
            onMouseEnter: () => setHoveredRowId(record.id),
            onMouseLeave: () => setHoveredRowId((prev) => (prev === record.id ? null : prev)),
          })}
          expandable={{
            expandedRowRender,
            expandedRowKeys,
            onExpandedRowsChange: (keys) => setExpandedRowKeys(keys as string[]),
            rowExpandable: () => true,
          }}
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

      {/* ── 导出 PDF Modal ── */}
      <Modal
        title={
          <span>
            <ExportOutlined style={{ marginRight: 8, color: '#5645D4' }} />
            导出 PDF
          </span>
        }
        open={exportModalOpen}
        onCancel={handleCloseExportModal}
        width={520}
        footer={[
          <Button key="cancel" onClick={handleCloseExportModal}>
            取消
          </Button>,
          <Button
            key="export"
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExportPdf}
          >
            导出 PDF
          </Button>,
        ]}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <Text strong style={{ display: 'block', marginBottom: 6 }}>
              用自然语言描述要导出哪些记录：
            </Text>
            <Input.TextArea
              placeholder={'例如：\n- "上月所有重大风险记录"\n- "合成岗位最近三个月的数据"\n- "生产部一级和二级风险的危险源"'}
              value={naturalQuery}
              onChange={(e) => setNaturalQuery(e.target.value)}
              rows={3}
            />
            <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
              留空则导出全部已完成记录；输入自然语言后点击「导出 PDF」，AI 将自动解析筛选条件并导出。
            </Text>
          </div>

          {exporting && (
            <div style={{ textAlign: 'center', padding: 16 }}>
              <Spin description={exportStep || '正在导出…'} />
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
