'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App, Button, Empty, Input, InputNumber, Modal,
  Select, Space, Table, Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  EditOutlined, EyeOutlined, ReloadOutlined,
  SaveOutlined, SearchOutlined, SendOutlined, SyncOutlined,
} from '@ant-design/icons'
import { Column } from '@ant-design/charts'
import dayjs, { type Dayjs } from 'dayjs'

import {
  deleteSpecialOperationReport,
  generateDailyReport,
  getDailyReportStats,
  getSpecialOperationLedgerStats,
  getSpecialOperationReports,
  syncDailyReportData,
  updateSpecialOperationReportV35,
} from '@/actions/safety'
import type {
  DailyReportResponse,
  DailyReportStats,
  SpecialOperationLedgerStats,
  SpecialOperationReport,
} from '@/types/safety'

import { OP_LEVEL_LABELS, OP_TYPE_CONFIG, OP_TYPE_KEYS } from './specialOpsConstants'

// ── DESIGN tokens（对齐 AiAuditPanel）──

const UI = {
  ink: '#1a1a1a',
  charcoal: '#37352f',
  slate: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
  canvas: '#ffffff',
  hairline: '#e5e3df',
  hairlineSoft: '#ede9e4',
  success: '#1aae39',
  warning: '#dd5b00',
  error: '#e03131',
  brandPurple: '#7b3ff2',
} as const

const CARD_STYLE: React.CSSProperties = {
  background: UI.canvas,
  border: `1px solid ${UI.hairline}`,
  borderRadius: 12,
}

const MONO_FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

// ── 日报风险色 ──

const RISK_COLORS: Record<string, string> = { high: '#e03131', medium: '#dd5b00', low: '#1aae39' }
const RISK_LABELS: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }

// ── V3.5 字段选项 ──
const FIRE_METHOD_OPTIONS = [
  { value: '电焊', label: '电焊' }, { value: '气割', label: '气割' },
  { value: '等离子切割机', label: '等离子切割机' }, { value: '氩弧焊', label: '氩弧焊' },
  { value: '切割机', label: '切割机' }, { value: '角磨机', label: '角磨机' },
  { value: '电钻', label: '电钻' }, { value: '冲击钻', label: '冲击钻' },
  { value: '塑料焊', label: '塑料焊' }, { value: '其他', label: '其他' },
]
const HEIGHT_METHOD_OPTIONS = [
  { value: '门式脚手架', label: '门式脚手架' }, { value: '扣件式脚手架', label: '扣件式脚手架' },
  { value: '高处作业车', label: '高处作业车' }, { value: '固定式直爬梯', label: '固定式直爬梯' },
  { value: '便携式钢直梯', label: '便携式钢直梯' }, { value: '其他', label: '其他' },
]

// ── KPI 卡（对齐 AiAuditPanel）──

function KpiCard({ label, value, caption, color, bg, onClick }: {
  label: string; value: React.ReactNode; caption?: React.ReactNode; color?: string; bg?: string; onClick?: () => void
}) {
  return (
    <div
      style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? UI.canvas, cursor: onClick ? 'pointer' : undefined }}
      onClick={onClick}
    >
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: color ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

// ── 场景 Tag ──

function RiskTag({ level }: { level?: string | null }) {
  if (!level) return <span style={{ color: UI.stone }}>—</span>
  return (
    <span style={{
      display: 'inline-block', fontSize: 12, fontWeight: 600, padding: '2px 10px', borderRadius: 9999,
      background: level === 'high' ? '#fef2f2' : level === 'medium' ? '#fff7ed' : '#f0fdf4',
      color: RISK_COLORS[level] ?? UI.steel,
    }}>
      {RISK_LABELS[level] ?? level}
    </span>
  )
}

function TypeTag({ type }: { type: string }) {
  const cfg = OP_TYPE_CONFIG[type]
  if (!cfg) return <span style={{ fontSize: 12 }}>{type}</span>
  return (
    <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color, background: cfg.bg, padding: '2px 10px', borderRadius: 9999 }}>
      {cfg.label}
    </span>
  )
}

// ═══════════════════════════════════════════════════════════

interface SpecialOpsManagementProps {
  initialStats?: SpecialOperationLedgerStats[]
}

export default function SpecialOpsManagement({ initialStats }: SpecialOpsManagementProps) {
  const { message, modal } = App.useApp()

  // ── 列表 ──
  const [rows, setRows] = useState<SpecialOperationReport[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)

  // ── 统计 ──
  const [stats, setStats] = useState<SpecialOperationLedgerStats[]>(initialStats || [])
  const [dailyStats, setDailyStats] = useState<DailyReportStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  // ── 筛选 ──
  const [opType, setOpType] = useState<string | undefined>()
  const [opLevel, setOpLevel] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // ── 操作 ──
  const [syncing, setSyncing] = useState(false)
  const [generating, setGenerating] = useState(false)

  // ── 弹窗 ──
  const [reportOpen, setReportOpen] = useState(false)
  const [dailyReport, setDailyReport] = useState<DailyReportResponse | null>(null)

  // ── 详情抽屉（简单 Modal 替代 Drawer，对齐 AI 审计风格）──
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<SpecialOperationReport | null>(null)

  // ── V3.5 字段编辑 ──
  const [v35Saving, setV35Saving] = useState(false)
  const [editV35, setEditV35] = useState(false)
  const [v35Form, setV35Form] = useState<{
    fire_work_method?: string | null
    height_work_method?: string | null
    work_height?: number | null
    lifting_weight?: number | null
    contractor_name?: string | null
  }>({})

  // ── 数据加载 ──
  const loadList = useCallback(async (p: number, ps: number) => {
    setLoading(true)
    try {
      const res = await getSpecialOperationReports({
        page: p, page_size: ps,
        operation_type: opType, operation_level: opLevel,
        keyword: keyword.trim() || undefined,
      })
      if (res.code === 200) {
        setRows(res.data || [])
        setTotal(res.meta?.total || 0)
      } else { message.error(res.message || '获取数据失败') }
    } finally { setLoading(false) }
  }, [opType, opLevel, keyword, message])

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const [ledgerRes, dailyRes] = await Promise.all([
        getSpecialOperationLedgerStats(),
        getDailyReportStats(),
      ])
      if (ledgerRes.code === 200 && ledgerRes.data) setStats(ledgerRes.data)
      if (dailyRes.code === 200 && dailyRes.data) setDailyStats(dailyRes.data)
    } finally { setStatsLoading(false) }
  }, [])

  useEffect(() => {
    setPage(1)
    void loadList(1, pageSize)
    void loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opType, opLevel])

  const refresh = () => { void loadList(page, pageSize); void loadStats() }

  // ── 操作 ──
  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncDailyReportData()
      if (res.code === 200) { message.success(`同步完成：${res.data?.synced_count || 0} 条`); refresh() }
      else { message.error(res.message || '同步失败') }
    } catch { message.error('同步失败') }
    finally { setSyncing(false) }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await generateDailyReport({ mode: 'today' })
      if (res.code === 200) { setDailyReport(res.data); setReportOpen(true); loadStats() }
      else { message.error(res.message || '生成失败') }
    } catch { message.error('生成失败') }
    finally { setGenerating(false) }
  }

  // ── V3.5 字段编辑 ──
  useEffect(() => {
    if (detailItem) {
      setV35Form({
        fire_work_method: detailItem.fire_work_method ?? null,
        height_work_method: detailItem.height_work_method ?? null,
        work_height: detailItem.work_height ?? null,
        lifting_weight: detailItem.lifting_weight ?? null,
        contractor_name: detailItem.contractor_name ?? null,
      })
      setEditV35(false)
    }
  }, [detailItem])

  const handleSaveV35 = async () => {
    if (!detailItem) return
    setV35Saving(true)
    try {
      const res = await updateSpecialOperationReportV35(detailItem.id, v35Form)
      if (res.code === 200 && res.data) {
        message.success('V3.5 字段已保存，风险等级将重新判定')
        setDetailItem(res.data)
        setEditV35(false)
        refresh()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setV35Saving(false)
    }
  }

  const handleDelete = async () => {
    if (!detailItem) return
    modal.confirm({
      title: '确认删除',
      content: `确定要删除作业记录「${detailItem.report_no || detailItem.id.slice(0, 8)}」吗？`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      centered: true,
      onOk: async () => {
        try {
          const res = await deleteSpecialOperationReport(detailItem.id)
          if (res.code === 200) {
            message.success('删除成功')
            setDetailOpen(false)
            setDetailItem(null)
            refresh()
          } else {
            message.error(res.message || '删除失败')
          }
        } catch { message.error('删除失败') }
      },
    })
  }

  // ── 表格 ──
  const columns: ColumnsType<SpecialOperationReport> = [
    {
      title: '申请编号', dataIndex: 'report_no', width: 140,
      render: (v: string, r) => (
        <a onClick={() => { setDetailItem(r); setDetailOpen(true) }}
          style={{ fontFamily: MONO_FONT, fontSize: 13, color: UI.ink, cursor: 'pointer' }}>{v}</a>
      ),
    },
    { title: '作业类型', dataIndex: 'operation_type', width: 100, render: (v: string) => <TypeTag type={v} /> },
    { title: '级别', dataIndex: 'operation_level', width: 60, render: (v: string) => <span style={{ fontSize: 12, color: UI.slate }}>{OP_LEVEL_LABELS[v] || v}</span> },
    { title: '地点', dataIndex: 'location', width: 100, ellipsis: true },
    { title: '作业内容', dataIndex: 'work_description', ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 13 }}>{v ?? '—'}</span> },
    { title: '部门', dataIndex: 'department', width: 90, ellipsis: true, render: (v: string) => <span style={{ fontSize: 12, color: UI.slate }}>{v ?? '—'}</span> },
    {
      title: '时间', dataIndex: 'planned_start_time', width: 100,
      render: (v: string, r) => {
        const start = v ? dayjs(v).format('MM/DD HH:mm') : ''
        const end = r.planned_end_time ? dayjs(r.planned_end_time).format('HH:mm') : ''
        return <span style={{ fontSize: 12, color: UI.slate, fontVariantNumeric: 'tabular-nums' }}>{start}{end ? ` ~ ${end}` : ''}</span>
      },
    },
    { title: '时长', dataIndex: 'work_duration_hours', width: 50, render: (v: number | null) => <span style={{ fontSize: 12, color: UI.steel }}>{v != null ? `${v}h` : '—'}</span> },
    { title: '人员', dataIndex: 'personnel_type', width: 72, render: (v: string) => <span style={{ fontSize: 12, color: v === '非公司人员' ? UI.warning : UI.slate }}>{v ?? '—'}</span> },
    { title: '风险', dataIndex: 'daily_risk_level', width: 90, render: (v: string | null) => <RiskTag level={v} /> },
    {
      title: '', key: 'action', width: 48, fixed: 'right' as const,
      render: (_, r) => (
        <Button type="text" size="small" icon={<EyeOutlined style={{ color: UI.steel }} />}
          onClick={() => { setDetailItem(r); setDetailOpen(true) }} />
      ),
    },
  ]

  // ── 统计卡数据 ──
  const statsMap = useMemo(() => Object.fromEntries(
    OP_TYPE_KEYS.map((key) => {
      const st = stats.find((s) => s.operation_type === key)
      return [key, { count: st?.count || 0, critical: st?.critical_count || 0 }]
    })
  ), [stats])

  // ── 趋势图数据（按作业类型按日堆叠）──
  // 简化版：以现有数据聚合日期计数
  const chartData = useMemo(() => {
    const grouped: Record<string, Record<string, number>> = {}
    for (const r of rows) {
      const d = r.planned_start_time ? dayjs(r.planned_start_time).format('MM/DD') : '未知'
      const t = r.operation_type || 'other'
      grouped[d] = grouped[d] || {}
      grouped[d][t] = (grouped[d][t] || 0) + 1
    }
    const result: { date: string; type: string; label: string; count: number }[] = []
    for (const [date, types] of Object.entries(grouped)) {
      for (const [type, count] of Object.entries(types)) {
        result.push({ date, type, label: OP_TYPE_CONFIG[type]?.label || type, count })
      }
    }
    return result.sort((a, b) => a.date.localeCompare(b.date))
  }, [rows])

  const chartConfig = chartData.length > 0 ? {
    data: chartData,
    xField: 'date', yField: 'count', colorField: 'label',
    stack: true,
    axis: {
      y: { labelStyle: { fill: UI.stone, fontSize: 11 }, grid: { stroke: UI.hairlineSoft, lineWidth: 0.5 } },
      x: { labelStyle: { fill: UI.stone, fontSize: 11 }, line: { stroke: UI.hairlineSoft } },
    },
    legend: { position: 'top' as const, itemLabelFill: UI.slate, itemLabelFontSize: 12 },
    interaction: { tooltip: { marker: false } },
    style: { view: { fill: 'transparent' } },
  } : null

  return (
    <div style={{ padding: 24 }}>

      {/* ── 页头 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>特殊作业管理</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            飞书多维表格数据同步 · 风险分析 · 日报推送
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh} title="刷新" />
      </div>

      {/* ── KPI 指标带 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {OP_TYPE_KEYS.map((key) => {
          const cfg = OP_TYPE_CONFIG[key]
          const st = statsMap[key] || { count: 0, critical: 0 }
          return (
            <KpiCard
              key={key}
              label={cfg.label}
              value={st.count}
              color={cfg.color}
              caption={st.critical > 0 ? `${st.critical} 项关键` : undefined}
              onClick={() => setOpType(opType === key ? undefined : key)}
            />
          )
        })}
      </div>

      {/* ── 日报摘要 + 操作按钮 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'stretch' }}>
        <KpiCard
          label="今日作业"
          value={dailyStats?.total ?? '—'}
          color={UI.ink}
          caption="已同步并完成风险判定"
        />
        <KpiCard
          label="高风险"
          value={dailyStats?.high ?? '—'}
          color={RISK_COLORS.high}
          bg={dailyStats && dailyStats.high > 0 ? '#fef2f2' : undefined}
          caption={dailyStats && dailyStats.high > 0 ? '需重点关注' : '暂无高风险作业'}
          onClick={() => setOpType(undefined)}
        />
        <KpiCard
          label="中风险"
          value={dailyStats?.medium ?? '—'}
          color={RISK_COLORS.medium}
          bg={dailyStats && dailyStats.medium > 0 ? '#fff7ed' : undefined}
          caption={dailyStats && dailyStats.medium > 0 ? '正常监护' : '暂无中风险作业'}
        />
        <KpiCard
          label="低风险"
          value={dailyStats?.low ?? '—'}
          color={RISK_COLORS.low}
          bg={dailyStats && dailyStats.low > 0 ? '#f0fdf4' : undefined}
        />
        <div style={{
          ...CARD_STYLE,
          flex: '0 0 auto', minWidth: 140,
          display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 8,
          padding: '14px 16px',
          background: '#fafaf8',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone, marginBottom: 4 }}>操作</div>
          <Button icon={<SyncOutlined spin={syncing} />} onClick={handleSync} loading={syncing}
            size="small" style={{ borderRadius: 6 }}>同步飞书</Button>
          <Button type="primary" icon={<SendOutlined />} onClick={handleGenerate} loading={generating}
            size="small" style={{ borderRadius: 6, fontWeight: 500, background: UI.brandPurple }}>生成日报</Button>
        </div>
      </div>

      {/* ── 趋势图 ── */}
      {chartConfig && (
        <div style={{ ...CARD_STYLE, padding: '16px 20px', marginBottom: 16 }}>
          <Column {...chartConfig} height={200} />
        </div>
      )}
      {!chartConfig && (
        <div style={{ ...CARD_STYLE, padding: '48px 20px', marginBottom: 16, textAlign: 'center' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="时间窗内暂无记录" />
        </div>
      )}

      {/* ── 记录卡（筛选栏并入卡头）── */}
      <div style={{ ...CARD_STYLE, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <Space wrap>
            <Select allowClear placeholder="作业类型" style={{ width: 130 }} value={opType} onChange={setOpType}
              options={Object.entries(OP_TYPE_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))} />
            <Select allowClear placeholder="作业级别" style={{ width: 110 }} value={opLevel} onChange={setOpLevel}
              options={Object.entries(OP_LEVEL_LABELS).map(([k, v]) => ({ value: k, label: v }))} />
            <Input.Search placeholder="搜索内容/地点" style={{ width: 220 }} value={keyword}
              onChange={(e) => setKeyword(e.target.value)} onSearch={() => { setPage(1); void loadList(1, pageSize) }} allowClear />
          </Space>
          <span style={{ fontSize: 12, color: UI.steel }}>共 {total} 条</span>
        </div>

        <Table<SpecialOperationReport>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1100 }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); void loadList(p, ps) },
          }}
        />
      </div>

      {/* ── 详情 Modal ── */}
      <Modal title="作业详情" open={detailOpen} onCancel={() => { setDetailOpen(false); setEditV35(false) }} width={640}
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button danger onClick={handleDelete}>删除记录</Button>
            <Space>
              {detailItem?.source === 'bitable' && !editV35 && (
                <Button icon={<EditOutlined />} onClick={() => setEditV35(true)}>编辑风险参数</Button>
              )}
              {detailItem?.source === 'bitable' && editV35 && (
                <>
                  <Button onClick={() => setEditV35(false)} disabled={v35Saving}>取消</Button>
                  <Button type="primary" icon={<SaveOutlined />} loading={v35Saving}
                    onClick={handleSaveV35}
                    style={{ background: UI.brandPurple, fontWeight: 500 }}>
                    保存风险参数
                  </Button>
                </>
              )}
              <Button onClick={() => { setDetailOpen(false); setEditV35(false) }}>关闭</Button>
            </Space>
          </div>
        }
      >
        {detailItem && (
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px 12px', fontSize: 13 }}>
            <span style={{ color: UI.stone }}>申请编号</span>
            <span style={{ fontFamily: MONO_FONT, color: UI.ink }}>{detailItem.report_no || '—'}</span>
            <span style={{ color: UI.stone }}>作业类型</span>
            <span><TypeTag type={detailItem.operation_type} /></span>
            <span style={{ color: UI.stone }}>作业级别</span>
            <span style={{ color: UI.slate }}>{OP_LEVEL_LABELS[detailItem.operation_level] || detailItem.operation_level || '—'}</span>
            <span style={{ color: UI.stone }}>作业地点</span>
            <span style={{ color: UI.ink }}>{detailItem.location || '—'}</span>
            <span style={{ color: UI.stone }}>作业部门</span>
            <span style={{ color: UI.ink }}>{detailItem.department || '—'}</span>
            <span style={{ color: UI.stone }}>计划时间</span>
            <span style={{ color: UI.slate }}>
              {detailItem.planned_start_time ? dayjs(detailItem.planned_start_time).format('YYYY-MM-DD HH:mm') : '—'}
              {' — '}
              {detailItem.planned_end_time ? dayjs(detailItem.planned_end_time).format('HH:mm') : '—'}
            </span>
            <span style={{ color: UI.stone }}>作业时长</span>
            <span style={{ color: UI.ink }}>{detailItem.work_duration_hours != null ? `${detailItem.work_duration_hours}h` : '—'}</span>
            <span style={{ color: UI.stone }}>人员类型</span>
            <span style={{ color: detailItem.personnel_type === '非公司人员' ? UI.warning : UI.ink }}>{detailItem.personnel_type || '—'}</span>
            <span style={{ color: UI.stone }}>作业内容</span>
            <span style={{ color: UI.ink, gridColumn: 'span 1' }}>{detailItem.work_description || '—'}</span>

            {detailItem.source === 'bitable' && (
              <>
                <span style={{ color: UI.stone }}>日报风险</span>
                <span><RiskTag level={detailItem.daily_risk_level} /></span>
                <span style={{ color: UI.stone }}>风险依据</span>
                <span style={{ color: UI.slate, fontSize: 12 }}>{detailItem.daily_risk_reason || '—'}</span>
                {detailItem.inferred_operation_types && (detailItem.inferred_operation_types as unknown as string[]).length > 0 && (
                  <>
                    <span style={{ color: UI.stone }}>推断类型</span>
                    <span>{(detailItem.inferred_operation_types as unknown as string[]).map((t: string) => (
                      <span key={t} style={{ fontSize: 12, color: UI.brandPurple, background: '#e6e0f5', padding: '2px 8px', borderRadius: 9999, marginRight: 6 }}>{t}</span>
                    ))}</span>
                  </>
                )}
                <span style={{ color: UI.stone }}>特殊时段</span>
                <span style={{ color: UI.ink }}>{detailItem.is_weekend_holiday === '是' ? '是' : '否'}</span>
                <span style={{ color: UI.stone }}>报备类型</span>
                <span style={{ color: UI.ink }}>{detailItem.report_type === 'planned' ? '计划内' : detailItem.report_type === 'unplanned' ? '计划外' : '—'}</span>
                {detailItem.is_excluded && (
                  <>
                    <span style={{ color: UI.stone }}>排除原因</span>
                    <span style={{ color: UI.warning, fontSize: 12 }}>{detailItem.exclusion_reason || '—'}</span>
                  </>
                )}
                {/* V3.5 字段 */}
                <span style={{ color: UI.stone, fontWeight: 600, gridColumn: '1 / -1', marginTop: 8, paddingTop: 8, borderTop: `1px solid ${UI.hairlineSoft}` }}>
                  V3.5 风险判定参数
                </span>
                <span style={{ color: UI.stone }}>动火方式</span>
                {editV35 ? (
                  <Select size="small" style={{ width: '100%' }} allowClear placeholder="选择动火方式"
                    value={v35Form.fire_work_method} onChange={(v) => setV35Form(f => ({ ...f, fire_work_method: v }))}
                    options={FIRE_METHOD_OPTIONS} />
                ) : (
                  <span style={{ color: v35Form.fire_work_method ? UI.ink : UI.steel }}>{v35Form.fire_work_method || '—'}</span>
                )}
                <span style={{ color: UI.stone }}>高处作业方式</span>
                {editV35 ? (
                  <Select size="small" style={{ width: '100%' }} allowClear placeholder="选择登高方式"
                    value={v35Form.height_work_method} onChange={(v) => setV35Form(f => ({ ...f, height_work_method: v }))}
                    options={HEIGHT_METHOD_OPTIONS} />
                ) : (
                  <span style={{ color: v35Form.height_work_method ? UI.ink : UI.steel }}>{v35Form.height_work_method || '—'}</span>
                )}
                <span style={{ color: UI.stone }}>作业高度(米)</span>
                {editV35 ? (
                  <InputNumber size="small" style={{ width: '100%' }} min={0} max={200} placeholder="米"
                    value={v35Form.work_height} onChange={(v) => setV35Form(f => ({ ...f, work_height: v }))} />
                ) : (
                  <span style={{ color: v35Form.work_height != null ? UI.ink : UI.steel }}>{v35Form.work_height != null ? `${v35Form.work_height}m` : '—'}</span>
                )}
                <span style={{ color: UI.stone }}>吊物质量(吨)</span>
                {editV35 ? (
                  <InputNumber size="small" style={{ width: '100%' }} min={0} max={1000} placeholder="吨"
                    value={v35Form.lifting_weight} onChange={(v) => setV35Form(f => ({ ...f, lifting_weight: v }))} />
                ) : (
                  <span style={{ color: v35Form.lifting_weight != null ? UI.ink : UI.steel }}>{v35Form.lifting_weight != null ? `${v35Form.lifting_weight}t` : '—'}</span>
                )}
                <span style={{ color: UI.stone }}>施工单位</span>
                {editV35 ? (
                  <Input size="small" style={{ width: '100%' }} placeholder="施工单位"
                    value={v35Form.contractor_name ?? ''} onChange={(e) => setV35Form(f => ({ ...f, contractor_name: e.target.value || null }))} />
                ) : (
                  <span style={{ color: v35Form.contractor_name ? UI.ink : UI.steel }}>{v35Form.contractor_name || '—'}</span>
                )}
              </>
            )}
          </div>
        )}
      </Modal>

      {/* ── 日报弹窗 ── */}
      <Modal title="📋 特殊作业日报" open={reportOpen} onCancel={() => setReportOpen(false)} width={700}
        footer={<Button onClick={() => setReportOpen(false)}>关闭</Button>}>
        {dailyReport && (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Tag color="red">{dailyReport.high_risk} 高风险</Tag>
              <Tag color="gold">{dailyReport.medium_risk} 中风险</Tag>
              <Tag color="green">{dailyReport.low_risk} 低风险</Tag>
              <span style={{ fontSize: 12, color: UI.steel }}>共 {dailyReport.total} 条 · 排除 {dailyReport.excluded} 条</span>
            </Space>
            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: MONO_FONT, fontSize: 13, lineHeight: 1.8, margin: 0,
              background: '#fafafa', padding: 16, borderRadius: 8, maxHeight: '60vh', overflow: 'auto' }}>
              {dailyReport.markdown_report}
            </pre>
          </>
        )}
      </Modal>
    </div>
  )
}
