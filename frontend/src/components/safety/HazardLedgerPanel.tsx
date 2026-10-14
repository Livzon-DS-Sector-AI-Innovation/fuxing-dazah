'use client'

import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  Input,
  Button,
  Space,
  App,
  Typography,
  Descriptions,
  DatePicker,
  Checkbox,
  Popover,
  Drawer,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  ExportOutlined,
  FilterOutlined,
  CloseCircleOutlined,
  CaretUpFilled,
  CaretDownFilled,
  FilePdfOutlined,
  FileExcelOutlined,
} from '@ant-design/icons'
import { ListChecks, TriangleAlert } from 'lucide-react'
import {
  getHazardIdentifications,
  getHILedgerStats,
  exportHazardLedgerPdf,
  exportHazardLedgerExcel,
} from '@/actions/safety'
import type { HazardIdentification, HazardLedgerStats } from '@/types/safety'
import { RISK_LEVEL_OPTIONS } from '@/types/safety'
import dayjs from 'dayjs'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── 风险等级语义 tone（表格内 StatusTag；红/橙/蓝/绿 对齐原四色）──
const RISK_TONE: Record<string, Tone> = {
  level_1: 'danger',
  level_2: 'warn',
  level_3: 'info',
  level_4: 'ok',
}

// ── 福建固有风险等级语义 tone（脚本3.5，中文等级名；低=蓝/一般、较大=警示/重大=红）──
const FJ_LEVEL_TONE: Record<string, Tone> = {
  低风险: 'info',
  一般风险: 'warn',
  较大风险: 'warn',
  重大风险: 'danger',
}

// ── 统计卡配置（点击卡片 = 按等级快捷筛选，沿用统计药丸交互） ──
const STATS_CARDS: Array<{ key: string; label: string; tone: Tone }> = [
  { key: '',        label: '全部',     tone: 'default' },
  { key: 'level_1', label: '重大风险', tone: 'danger' },
  { key: 'level_2', label: '较大风险', tone: 'warn' },
  { key: 'level_3', label: '一般风险', tone: 'info' },
  { key: 'level_4', label: '低风险',   tone: 'ok' },
]

// ── 管控层级语义 tone（公司级红/部门级橙/班组级蓝）──
const CONTROL_LEVEL_TONE: Record<string, Tone> = {
  '公司级': 'danger',
  '部门级': 'warn',
  '班组级': 'info',
}

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
  inherent_risk_level_fj: '福建固有风险',
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

  // ── 导出 Drawer 状态（独立于主表格勾选，翻页保持）──
  const [exportDrawerOpen, setExportDrawerOpen] = useState(false)
  const [exportSelectedKeys, setExportSelectedKeys] = useState<React.Key[]>([])
  const [exportPage, setExportPage] = useState(1)
  const [exportPageSize, setExportPageSize] = useState(20)
  const [exportTotal, setExportTotal] = useState(0)
  const [exportData, setExportData] = useState<HazardIdentification[]>([])
  const [exportDrawerLoading, setExportDrawerLoading] = useState(false)
  const [exporting, setExporting] = useState<'pdf' | 'excel' | null>(null)
  // 抽屉内部门/岗位筛选
  const [exportDrawerDepartment, setExportDrawerDepartment] = useState('')
  const [exportDrawerPosition, setExportDrawerPosition] = useState('')

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

  // ── 导出 Drawer：加载已完成记录（可带部门/岗位筛选）──
  const loadExportDrawerData = useCallback(async (page: number, pageSize: number) => {
    setExportDrawerLoading(true)
    try {
      const res = await getHazardIdentifications({
        page,
        page_size: pageSize,
        overall_status: 'completed',
        department: exportDrawerDepartment.trim() || undefined,
        position: exportDrawerPosition.trim() || undefined,
      })
      if (res.code === 200) {
        setExportData((res.data as HazardIdentification[]) || [])
        setExportTotal(res.meta?.total || 0)
      }
    } catch {
      msgApi.error('加载导出列表失败')
    } finally {
      setExportDrawerLoading(false)
    }
  }, [exportDrawerDepartment, exportDrawerPosition, msgApi])

  const openExportDrawer = () => {
    setExportSelectedKeys([])
    setExportPage(1)
    setExportDrawerOpen(true)
    loadExportDrawerData(1, exportPageSize)
  }

  const closeExportDrawer = () => {
    setExportDrawerOpen(false)
    setExportSelectedKeys([])
    setExportDrawerDepartment('')
    setExportDrawerPosition('')
  }

  // ── 统一导出（PDF / Excel 相同方式，按抽屉勾选 ids）──
  const handleExport = async (format: 'pdf' | 'excel') => {
    const ids = exportSelectedKeys as string[]
    if (ids.length === 0) {
      msgApi.warning('请先选择要导出的记录')
      return
    }
    setExporting(format)
    try {
      const result = format === 'pdf'
        ? await exportHazardLedgerPdf({ ids })
        : await exportHazardLedgerExcel({ ids })
      downloadBase64(
        result.data || '',
        `危险源辨识台账_选中${ids.length}条_${new Date().toISOString().slice(0, 10)}.${format === 'pdf' ? 'pdf' : 'xlsx'}`,
        format === 'pdf'
          ? 'application/pdf'
          : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      )
      msgApi.success(`成功导出 ${ids.length} 条记录`)
      closeExportDrawer()
    } catch {
      msgApi.error(`${format.toUpperCase()} 导出失败`)
    } finally {
      setExporting(null)
    }
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

  const handlePillClick = (pill: { key: string }) => {
    if (pill.key === '') {
      setRiskLevel(undefined)
    } else {
      setRiskLevel(riskLevel === pill.key ? undefined : pill.key)
    }
    setQueryParams({ page: 1, page_size: queryParams.page_size })
  }

  const getRiskTag = (level?: string, label?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <StatusTag tone={RISK_TONE[level] ?? 'default'} label={label || opt?.label || level} />
  }

  const getRiskPill = (level?: string, label?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <StatusTag tone={RISK_TONE[level] ?? 'default'} label={label || opt?.label || level} />
  }

  // ── 福建固有风险等级标签（脚本3.5：中文名语义映射，独立于 RISK_TONE）──
  const getFjRiskPill = (level?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    return <StatusTag tone={FJ_LEVEL_TONE[level] ?? 'default'} label={level} />
  }

  const getControlLevelTag = (level?: string) => {
    if (!level) return <span style={{ color: '#a4a097' }}>-</span>
    return <StatusTag tone={CONTROL_LEVEL_TONE[level] ?? 'default'} label={level} />
  }

  // ── 表格列定义 ──
  const columns: ColumnsType<HazardIdentification> = [
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
      title: '福建固有风险',
      key: 'inherent_risk_fj',
      width: 110,
      render: (_, r) => getFjRiskPill(r.inherent_risk_level_fj),
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

          {record.inherent_risk_level_fj && (
            <Descriptions size="small" column={6} colon={false} title={<Text strong style={{ fontSize: 13 }}>福建固有风险评级（脚本3.5）</Text>} style={{ marginBottom: 0 }}>
              <Descriptions.Item label="等级" span={6}>
                {getFjRiskPill(record.inherent_risk_level_fj)}
              </Descriptions.Item>
            </Descriptions>
          )}

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
                  <StatusTag label={record.recommendation_priority} />
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
    <div>
      {/* ── 页头 ── */}
      <PageHeader
        breadcrumb={['安全管理', '风险分级管控']}
        title="风险分级管控"
        description="风险辨识与分级管控台账：风险点全量、分级分布"
        actions={
          <Button type="primary" icon={<ExportOutlined />} onClick={openExportDrawer}>
            导出台账
          </Button>
        }
      />

      {/* ── 分级统计行（点击卡片 = 按等级快捷筛选，沿用统计药丸交互） ── */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {STATS_CARDS.map((card) => {
          const isActive = card.key === '' ? riskLevel === undefined : riskLevel === card.key
          const count = getPillCount(card.key)
          return (
            <StatCard
              key={card.key || 'all'}
              label={card.label}
              value={count}
              tone={card.key === '' || count > 0 ? card.tone : 'default'}
              sub={
                card.key === ''
                  ? riskLevel === undefined
                    ? '当前展示全部等级'
                    : '点击清除等级筛选'
                  : isActive
                    ? '筛选中 · 点击取消'
                    : '点击按等级筛选'
              }
              icon={
                card.key === ''
                  ? <ListChecks size={16} />
                  : card.key === 'level_1'
                    ? <TriangleAlert size={16} />
                    : undefined
              }
              onClick={() => handlePillClick(card)}
            />
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

      {/* ── 台账明细 ── */}
      <SectionCard
        title="风险点台账"
        description={`已完成危险源辨识记录（共 ${total} 条）· 点编号看详情，展开行看评价与措施`}
      >
        {/* ── 全局样式 ── */}
        <style>{`
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
          locale={{
            emptyText: (
              <EmptyGuide
                compact
                title="暂无符合条件的风险点"
                description="调整搜索、日期或筛选条件后重试"
              />
            ),
          }}
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
      </SectionCard>

      {/* ── 导出 Drawer（勾选多行，翻页保持）── */}
      <Drawer
        title={
          <span>
            <ExportOutlined style={{ marginRight: 8, color: '#5645D4' }} />
            导出危险源辨识台账
          </span>
        }
        open={exportDrawerOpen}
        onClose={closeExportDrawer}
        placement="right"
        width={720}
        destroyOnHidden
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">已选 {exportSelectedKeys.length} 条</Text>
            <Space>
              <Button
                icon={<FileExcelOutlined />}
                loading={exporting === 'excel'}
                disabled={exportSelectedKeys.length === 0}
                onClick={() => handleExport('excel')}
              >
                导出 Excel
              </Button>
              <Button
                type="primary"
                icon={<FilePdfOutlined />}
                loading={exporting === 'pdf'}
                disabled={exportSelectedKeys.length === 0}
                onClick={() => handleExport('pdf')}
              >
                导出 PDF
              </Button>
            </Space>
          </div>
        }
      >
        {/* ── 抽屉内部门/岗位筛选 ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Input
            placeholder="筛选部门"
            prefix={<FilterOutlined style={{ color: '#a4a097' }} />}
            value={exportDrawerDepartment}
            onChange={(e) => setExportDrawerDepartment(e.target.value)}
            onPressEnter={() => {
              setExportPage(1)
              loadExportDrawerData(1, exportPageSize)
            }}
            allowClear
            style={{ width: 160, height: 32 }}
          />
          <Input
            placeholder="筛选岗位"
            prefix={<FilterOutlined style={{ color: '#a4a097' }} />}
            value={exportDrawerPosition}
            onChange={(e) => setExportDrawerPosition(e.target.value)}
            onPressEnter={() => {
              setExportPage(1)
              loadExportDrawerData(1, exportPageSize)
            }}
            allowClear
            style={{ width: 160, height: 32 }}
          />
          <Button
            size="small"
            onClick={() => {
              setExportPage(1)
              loadExportDrawerData(1, exportPageSize)
            }}
          >
            查询
          </Button>
          <Button
            size="small"
            type="text"
            onClick={() => {
              setExportDrawerDepartment('')
              setExportDrawerPosition('')
              setExportPage(1)
              loadExportDrawerData(1, exportPageSize)
            }}
          >
            重置
          </Button>
        </div>

        <Table
          rowKey="id"
          size="small"
          loading={exportDrawerLoading}
          dataSource={exportData}
          pagination={{
            current: exportPage,
            pageSize: exportPageSize,
            total: exportTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => {
              setExportPage(page)
              setExportPageSize(pageSize)
              loadExportDrawerData(page, pageSize)
            },
          }}
          columns={[
            // 自定义复选框列：手动 toggle 数组，翻页勾选保持
            {
              title: '',
              key: '__export_select__',
              width: 48,
              align: 'center',
              render: (_: unknown, record: HazardIdentification) => {
                const isSelected = exportSelectedKeys.includes(record.id)
                const handleToggle = () => {
                  setExportSelectedKeys((prev) =>
                    prev.includes(record.id)
                      ? prev.filter((k) => k !== record.id)
                      : [...prev, record.id]
                  )
                }
                return <Checkbox checked={isSelected} onChange={handleToggle} />
              },
            },
            { title: '编号', dataIndex: 'hazard_id_no', width: 160 },
            { title: '部门', dataIndex: 'department', width: 140, ellipsis: true },
            { title: '岗位', dataIndex: 'position', width: 140, ellipsis: true },
            { title: '生产步骤', dataIndex: 'production_step', ellipsis: true },
          ]}
        />
      </Drawer>
    </div>
  )
}
