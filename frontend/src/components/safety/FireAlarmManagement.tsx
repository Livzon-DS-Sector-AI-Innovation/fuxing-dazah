'use client'

import { useMemo, useState } from 'react'
import {
  App, Button, DatePicker, Empty, Input, Modal, Select, Space, Table, Tag, Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  EyeOutlined, FileTextOutlined, ReloadOutlined, SendOutlined, SyncOutlined,
} from '@ant-design/icons'
import { Column } from '@ant-design/charts'
import dayjs, { type Dayjs } from 'dayjs'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchFireAlarmRecords, fetchFireAlarmStats } from '@/lib/api/safety/fire-alarm'
import {
  generateFireAlarmDailyReport,
  generateFireAlarmWeeklyReport,
  syncFireAlarmData,
} from '@/actions/safety'
import type {
  FireAlarmPushResult,
  FireAlarmRecord,
  FireAlarmReportResponse,
  FireAlarmStats,
} from '@/types/safety'

import { T } from './shared-styles'
import { AI_DIMENSION_CONFIG, dynamicTagStyle, PUSH_RESULT } from './fireAlarmConstants'

// ── DESIGN tokens：统一从 shared-styles 的 T 导入（唯一来源），本地不重复定义色板 ──

const CARD_STYLE: React.CSSProperties = {
  background: T.canvas,
  border: `1px solid ${T.hairline}`,
  borderRadius: 12,
}

const MONO_FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

// ── KPI 卡（对齐 SpecialOpsManagement 内联 KpiCard）──

function KpiCard({ label, value, caption, color, bg }: {
  label: string; value: React.ReactNode; caption?: React.ReactNode; color?: string; bg?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? T.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: T.muted }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: color ?? T.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: T.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

// ── AI 维度 Tag（英文枚举 → 中文；未识别/空 → 灰「—」）──

function DimensionTag({ dimension }: { dimension?: string | null }) {
  const cfg = dimension ? AI_DIMENSION_CONFIG[dimension] : undefined
  if (!cfg) return <span style={{ fontSize: 12, color: T.muted }}>—</span>
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600,
      padding: '2px 10px', borderRadius: 9999, background: cfg.bg, color: cfg.text,
      whiteSpace: 'nowrap', width: 'fit-content',
    }}>
      {cfg.icon}{cfg.label}
    </span>
  )
}

// ── 动态配色 Tag（报警类型/报警性质自由文本；误报置灰、真实警情 error pill）──

function DynamicTag({ name }: { name: string }) {
  const style = dynamicTagStyle(name)
  return (
    <span style={{
      display: 'inline-block', fontSize: 12, fontWeight: 600,
      padding: '2px 10px', borderRadius: 9999, background: style.bg, color: style.text,
      whiteSpace: 'nowrap',
    }}>
      {name}
    </span>
  )
}

// ═══════════════════════════════════════════════════════════

interface FireAlarmManagementProps {
  initialStats?: FireAlarmStats | null
}

export default function FireAlarmManagement({ initialStats }: FireAlarmManagementProps) {
  const { message } = App.useApp()

  // ── 列表 ──
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // ── 筛选 ──
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [department, setDepartment] = useState<string | undefined>()
  const [alarmType, setAlarmType] = useState<string | undefined>()
  const [alarmNature, setAlarmNature] = useState<string | undefined>()
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')

  // ── 操作 ──
  const [syncing, setSyncing] = useState(false)
  const [generatingDaily, setGeneratingDaily] = useState(false)
  const [generatingWeekly, setGeneratingWeekly] = useState(false)

  // ── 弹窗 ──
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<FireAlarmRecord | null>(null)
  const [reportOpen, setReportOpen] = useState(false)
  const [report, setReport] = useState<FireAlarmReportResponse | null>(null)

  const queryClient = useQueryClient()

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['fire-alarms'] })
    queryClient.invalidateQueries({ queryKey: ['fire-alarm-stats'] })
  }

  // ── 统计 query（服务端预取做 initialData） ──
  const statsQuery = useQuery({
    queryKey: ['fire-alarm-stats'],
    queryFn: fetchFireAlarmStats,
    initialData: initialStats ?? undefined,
  })
  const stats = statsQuery.data ?? null

  // ── 列表 query ──
  const { data: listData, isLoading } = useQuery({
    queryKey: ['fire-alarms', {
      page, pageSize,
      dateFrom: dateRange?.[0] ? dateRange[0].format('YYYY-MM-DD') : undefined,
      dateTo: dateRange?.[1] ? dateRange[1].format('YYYY-MM-DD') : undefined,
      department, alarmType, alarmNature, keyword,
    }],
    queryFn: () => fetchFireAlarmRecords({
      page, page_size: pageSize,
      date_from: dateRange?.[0] ? dateRange[0].format('YYYY-MM-DD') : undefined,
      date_to: dateRange?.[1] ? dateRange[1].format('YYYY-MM-DD') : undefined,
      department: department || undefined,
      alarm_type: alarmType || undefined,
      alarm_nature: alarmNature || undefined,
      keyword: keyword.trim() || undefined,
    }),
  })

  const rows = useMemo(() => listData?.items ?? [], [listData?.items])
  const total = listData?.total ?? 0

  // ── 操作：同步飞书 ──
  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncFireAlarmData()
      if (res.code === 200) {
        const d = res.data
        message.success(
          `同步完成：更新 ${d?.synced_count ?? 0} 条${d?.soft_deleted_count ? `，软删除 ${d.soft_deleted_count} 条` : ''}`
        )
        refresh()
      } else {
        message.error(res.message || '同步失败')
      }
    } catch {
      message.error('同步失败')
    } finally {
      setSyncing(false)
    }
  }

  // ── 操作：生成日报/周报（同构流程，仅入口与参数不同）──
  const summarizePush = (results: FireAlarmPushResult[] | undefined): string => {
    if (!results || results.length === 0) return '未配置推送目标，已跳过推送'
    const ok = results.filter((r) => r.success).length
    const skipped = results.filter((r) => r.skipped).length
    if (ok > 0) {
      const failed = results.length - ok
      return `推送成功 ${ok} 群${failed > 0 ? `，${failed} 群失败` : ''}`
    }
    if (skipped === results.length) return '未配置推送目标，已跳过推送'
    return '推送失败'
  }

  const handleGenerate = async (kind: 'daily' | 'weekly') => {
    const setGenerating = kind === 'daily' ? setGeneratingDaily : setGeneratingWeekly
    const label = kind === 'daily' ? '日报' : '周报'
    setGenerating(true)
    message.loading({ content: 'AI 分析中，报警较多时可能需要 1-2 分钟…', key: 'fire-alarm-gen' })
    try {
      const res = kind === 'daily'
        ? await generateFireAlarmDailyReport({})
        : await generateFireAlarmWeeklyReport({})
      if (res.code === 200 && res.data) {
        message.destroy('fire-alarm-gen')
        message.success(`${label}已生成 · ${summarizePush(res.data.push_results)}`)
        setReport(res.data)
        setReportOpen(true)
        // 必须重拉列表：日报生成会回写每条记录的 AI 分析字段，「本周已AI分析」也随之变化
        refresh()
      } else {
        message.destroy('fire-alarm-gen')
        message.error(res.message || '生成失败')
      }
    } catch {
      message.destroy('fire-alarm-gen')
      message.error('生成失败')
    } finally {
      setGenerating(false)
    }
  }

  // ── 筛选器选项：stats 分布 + 已加载行内值取并集兜底（避免本周无数据的部门不可选）──
  const optionList = (dist: Record<string, number> | undefined, rowValues: (string | null | undefined)[]) => {
    const fromStats = Object.keys(dist || {})
    const fromRows = rowValues.filter((v): v is string => !!v)
    return [...new Set([...fromStats, ...fromRows])].map((v) => ({ value: v, label: v }))
  }

  const departmentOptions = useMemo(
    () => optionList(stats?.department_distribution, rows.map((r) => r.department)),
    [stats, rows]
  )
  const typeOptions = useMemo(
    () => optionList(stats?.type_distribution, rows.map((r) => r.alarm_type)),
    [stats, rows]
  )
  const natureOptions = useMemo(
    () => optionList(stats?.nature_distribution, rows.map((r) => r.alarm_nature)),
    [stats, rows]
  )

  // ── 性质分布卡（本周 Top 4 + 其他聚合；点击切换表格性质筛选）──
  const natureDistItems = useMemo(() => {
    const entries = Object.entries(stats?.nature_distribution || {}).sort((a, b) => b[1] - a[1])
    const top = entries.slice(0, 4)
    const rest = entries.slice(4)
    const items = top.map(([name, count]) => ({ name, count }))
    if (rest.length > 0) {
      items.push({ name: '其他', count: rest.reduce((s, [, c]) => s + c, 0) })
    }
    return items
  }, [stats])

  const handleNatureClick = (name: string) => {
    setAlarmNature(alarmNature === name ? undefined : name)
    setPage(1)
  }

  // ── 趋势图数据（按日 × 报警性质堆叠，由当前筛选结果聚合）──
  const chartData = useMemo(() => {
    const grouped: Record<string, Record<string, number>> = {}
    for (const r of rows) {
      const d = r.alarm_time ? dayjs(r.alarm_time).format('MM/DD') : '未知'
      const n = r.alarm_nature || '未知'
      grouped[d] = grouped[d] || {}
      grouped[d][n] = (grouped[d][n] || 0) + 1
    }
    const result: { date: string; nature: string; count: number }[] = []
    for (const [date, natures] of Object.entries(grouped)) {
      for (const [nature, count] of Object.entries(natures)) {
        result.push({ date, nature, count })
      }
    }
    return result.sort((a, b) => a.date.localeCompare(b.date))
  }, [rows])

  // 堆叠色复用 dynamicTagStyle 的 text 色，保证图例与表格 Tag 同色
  const natureNames = useMemo(() => [...new Set(chartData.map((d) => d.nature))], [chartData])
  const chartConfig = chartData.length > 0 ? {
    data: chartData,
    xField: 'date', yField: 'count', colorField: 'nature',
    stack: true,
    scale: {
      color: {
        domain: natureNames,
        range: natureNames.map((n) => dynamicTagStyle(n).text),
      },
      y: { domainMin: 0 },
    },
    axis: {
      y: { labelStyle: { fill: T.muted, fontSize: 11 }, grid: { stroke: T.hairlineSoft, lineWidth: 0.5 } },
      x: { labelStyle: { fill: T.muted, fontSize: 11 }, line: { stroke: T.hairlineSoft } },
    },
    legend: { position: 'top' as const, itemLabelFill: T.slate, itemLabelFontSize: 12 },
    interaction: { tooltip: { marker: false } },
    style: { view: { fill: 'transparent' } },
  } : null

  // ── 表格 ──
  const columns: ColumnsType<FireAlarmRecord> = [
    {
      title: '报警时间', dataIndex: 'alarm_time', width: 130,
      render: (v: string | null, r) => (
        <a onClick={() => { setDetailItem(r); setDetailOpen(true) }}
          style={{ fontFamily: MONO_FONT, fontSize: 13, color: T.ink, cursor: 'pointer', fontVariantNumeric: 'tabular-nums' }}>
          {v ? dayjs(v).format('MM/DD HH:mm') : '—'}
        </a>
      ),
    },
    { title: '报警类型', dataIndex: 'alarm_type', width: 100, render: (v: string | null) => v ? <DynamicTag name={v} /> : <span style={{ color: T.muted }}>—</span> },
    { title: '报警部门', dataIndex: 'department', width: 100, ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 12, color: T.slate }}>{v ?? '—'}</span> },
    { title: '报警楼栋', dataIndex: 'building', width: 90, ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 12, color: T.slate }}>{v ?? '—'}</span> },
    { title: '报警部位', dataIndex: 'location', width: 110, ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 12, color: T.slate }}>{v ?? '—'}</span> },
    { title: '报警性质', dataIndex: 'alarm_nature', width: 90, render: (v: string | null) => v ? <DynamicTag name={v} /> : <span style={{ color: T.muted }}>—</span> },
    { title: '原因分类', dataIndex: 'cause_category', width: 110, ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 12, color: T.slate }}>{v ?? '—'}</span> },
    {
      title: '具体报警原因', dataIndex: 'cause_description', minWidth: 200, ellipsis: true,
      render: (v: string | null) => v
        ? <Tooltip title={v}><span style={{ fontSize: 13, color: T.ink }}>{v}</span></Tooltip>
        : <span style={{ color: T.muted }}>—</span>,
    },
    {
      title: 'AI 分析', key: 'ai_analysis', width: 220,
      render: (_, r) => (r.ai_dimension || r.ai_reason_analysis || r.ai_rectification_direction)
        ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
            <DimensionTag dimension={r.ai_dimension} />
            {r.ai_rectification_direction && (
              <Tooltip title={r.ai_rectification_direction}>
                <div style={{
                  fontSize: 12, color: T.steel, maxWidth: 190,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>{r.ai_rectification_direction}</div>
              </Tooltip>
            )}
          </div>
        )
        : <span style={{ color: T.muted }}>—</span>,
    },
    {
      title: '', key: 'action', width: 48, fixed: 'right' as const,
      render: (_, r) => (
        <Button type="text" size="small" icon={<EyeOutlined style={{ color: T.steel }} />}
          onClick={() => { setDetailItem(r); setDetailOpen(true) }} />
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>

      {/* ── 页头 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: T.ink }}>消防报警分析</div>
          <div style={{ fontSize: 13, color: T.slate, marginTop: 2 }}>
            飞书多维表格数据同步 · AI 二次分析 · 日报/周报推送
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh} title="刷新" />
      </div>

      {/* ── KPI 指标带 + 操作卡 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'stretch' }}>
        <KpiCard label="今日报警" value={statsQuery.isLoading && !stats ? '—' : (stats?.today_total ?? '—')} caption="北京时间当日" />
        <KpiCard label="本周报警" value={stats?.week_total ?? '—'} color={T.primary} caption="自然周 周一~周日" />
        <KpiCard label="累计记录" value={stats?.total_count ?? '—'} caption="平台台账全量" />
        <KpiCard label="本周已AI分析" value={stats?.week_ai_analyzed_count ?? '—'} color={T.success} caption="生成日报后自动回写" />
        <div style={{
          ...CARD_STYLE,
          flex: '0 0 auto', minWidth: 150,
          display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 8,
          padding: '14px 16px',
          background: '#fafaf8',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: T.muted, marginBottom: 4 }}>操作</div>
          <Button icon={<SyncOutlined spin={syncing} />} onClick={handleSync} loading={syncing}
            size="small" style={{ borderRadius: 6 }}>同步飞书</Button>
          <Button type="primary" icon={<SendOutlined />} onClick={() => handleGenerate('daily')} loading={generatingDaily}
            size="small" style={{ borderRadius: 6, fontWeight: 500, background: T.primary }}>生成日报</Button>
          <Button icon={<FileTextOutlined />} onClick={() => handleGenerate('weekly')} loading={generatingWeekly}
            size="small" style={{ borderRadius: 6 }}>生成周报</Button>
        </div>
      </div>

      {/* ── 性质分布带（本周 Top 4 + 其他，点击过滤）── */}
      {natureDistItems.length > 0 && (
        <div style={{ ...CARD_STYLE, padding: '14px 16px', marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: T.muted, marginBottom: 10 }}>报警性质分布（本周）</div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {natureDistItems.map((item) => {
              const active = alarmNature === item.name
              const clickable = item.name !== '其他' // 聚合卡无法映射单一性质，仅展示
              return (
                <div
                  key={item.name}
                  onClick={clickable ? () => handleNatureClick(item.name) : undefined}
                  style={{
                    flex: 1, minWidth: 120, padding: '10px 14px', borderRadius: 10,
                    cursor: clickable ? 'pointer' : 'default',
                    background: active ? '#f3f0fe' : T.surface,
                    border: `1px solid ${active ? T.primary : T.hairline}`,
                  }}
                >
                  <div style={{ fontSize: 12, color: T.steel }}>{item.name}</div>
                  <div style={{ fontSize: 20, fontWeight: 600, color: T.ink, fontVariantNumeric: 'tabular-nums', marginTop: 2 }}>
                    {item.count}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── 趋势图卡（按日 × 报警性质堆叠）── */}
      <div style={{ ...CARD_STYLE, padding: '16px 20px', marginBottom: 16 }}>
        {chartConfig ? <Column {...chartConfig} height={200} /> : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="时间窗内暂无记录" style={{ padding: '24px 0' }} />
        )}
      </div>

      {/* ── 记录卡（筛选栏并入卡头）── */}
      <div style={{ ...CARD_STYLE, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <Space wrap>
            <DatePicker.RangePicker
              value={dateRange}
              onChange={(v) => { setDateRange(v as [Dayjs | null, Dayjs | null] | null); setPage(1) }}
              placeholder={['开始日期', '结束日期']}
              style={{ width: 240 }}
            />
            <Select allowClear showSearch placeholder="报警部门" style={{ width: 130 }} value={department}
              onChange={(v) => { setDepartment(v); setPage(1) }} options={departmentOptions} />
            <Select allowClear placeholder="报警类型" style={{ width: 120 }} value={alarmType}
              onChange={(v) => { setAlarmType(v); setPage(1) }} options={typeOptions} />
            <Select allowClear placeholder="报警性质" style={{ width: 110 }} value={alarmNature}
              onChange={(v) => { setAlarmNature(v); setPage(1) }} options={natureOptions} />
            <Input.Search placeholder="搜索原因/部位" style={{ width: 220 }} value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)} onSearch={() => { setKeyword(keywordInput); setPage(1) }} allowClear />
          </Space>
          <span style={{ fontSize: 12, color: T.steel }}>共 {total} 条</span>
        </div>

        <Table<FireAlarmRecord>
          rowKey="id"
          size="small"
          loading={isLoading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1300 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消防报警记录，可点击「同步飞书」拉取数据" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </div>

      {/* ── 详情 Modal（平台侧只读：数据以飞书多维表格为源）── */}
      <Modal title="报警详情" open={detailOpen}
        onCancel={() => { setDetailOpen(false); setDetailItem(null) }} width={640}
        footer={<Button onClick={() => { setDetailOpen(false); setDetailItem(null) }}>关闭</Button>}>
        {detailItem && (
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px 12px', fontSize: 13 }}>
            <span style={{ color: T.muted }}>报警时间</span>
            <span style={{ color: T.ink }}>{detailItem.alarm_time ? dayjs(detailItem.alarm_time).format('YYYY-MM-DD HH:mm') : '—'}</span>
            <span style={{ color: T.muted }}>报警类型</span>
            <span>{detailItem.alarm_type ? <DynamicTag name={detailItem.alarm_type} /> : '—'}</span>
            <span style={{ color: T.muted }}>报警部门</span>
            <span style={{ color: T.ink }}>{detailItem.department || '—'}</span>
            <span style={{ color: T.muted }}>部门负责人</span>
            <span style={{ color: T.ink }}>{detailItem.department_leader_name || '—'}</span>
            <span style={{ color: T.muted }}>报警楼栋</span>
            <span style={{ color: T.ink }}>{detailItem.building || '—'}</span>
            <span style={{ color: T.muted }}>报警部位</span>
            <span style={{ color: T.ink }}>{detailItem.location || '—'}</span>
            <span style={{ color: T.muted }}>报警性质</span>
            <span>{detailItem.alarm_nature ? <DynamicTag name={detailItem.alarm_nature} /> : '—'}</span>
            <span style={{ color: T.muted }}>原因分类</span>
            <span style={{ color: T.ink }}>{detailItem.cause_category || '—'}</span>
            <span style={{ color: T.muted }}>具体报警原因</span>
            <span style={{ color: T.ink }}>{detailItem.cause_description || '—'}</span>

            {/* AI 二次分析区块 */}
            <span style={{ color: T.muted, fontWeight: 600, gridColumn: '1 / -1', marginTop: 8, paddingTop: 8, borderTop: `1px solid ${T.hairlineSoft}` }}>
              AI 二次分析
            </span>
            {detailItem.ai_dimension || detailItem.ai_reason_analysis || detailItem.ai_rectification_direction ? (
              <>
                <span style={{ color: T.muted }}>分析维度</span>
                <span><DimensionTag dimension={detailItem.ai_dimension} /></span>
                <span style={{ color: T.muted }}>原因分析</span>
                <span style={{ color: T.slate }}>{detailItem.ai_reason_analysis || '—'}</span>
                <span style={{ color: T.muted }}>整改方向</span>
                <span style={{ color: T.ink }}>{detailItem.ai_rectification_direction || '—'}</span>
                <span style={{ color: T.muted }}>分析时间</span>
                <span style={{ color: T.steel }}>{detailItem.ai_analyzed_at ? dayjs(detailItem.ai_analyzed_at).format('MM/DD HH:mm') : '—'}</span>
              </>
            ) : (
              <span style={{ color: T.muted, fontSize: 12, gridColumn: '1 / -1' }}>尚未分析 — 生成日报后自动回写</span>
            )}

            {/* 同步信息 */}
            <span style={{ color: T.muted, fontWeight: 600, gridColumn: '1 / -1', marginTop: 8, paddingTop: 8, borderTop: `1px solid ${T.hairlineSoft}` }}>
              同步信息
            </span>
            <span style={{ color: T.muted }}>来源</span>
            <span style={{ fontSize: 12, color: T.slate }}>
              {detailItem.source === 'bitable' ? '飞书多维表格' : detailItem.source === 'manual' ? '手动录入' : detailItem.source || '—'}
            </span>
            <span style={{ color: T.muted }}>飞书记录ID</span>
            <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: T.steel, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {detailItem.feishu_record_id || '—'}
            </span>
            <span style={{ color: T.muted }}>同步时间</span>
            <span style={{ fontSize: 12, color: T.steel }}>{detailItem.synced_at ? dayjs(detailItem.synced_at).format('YYYY-MM-DD HH:mm') : '—'}</span>
          </div>
        )}
      </Modal>

      {/* ── 日报/周报 Modal（共用；关闭后数据保留，重复打开不重生成）── */}
      <Modal title={report?.report_kind === 'weekly' ? '📈 消防报警周报' : '📋 消防报警日报'}
        open={reportOpen} onCancel={() => setReportOpen(false)} width={720}
        footer={<Button onClick={() => setReportOpen(false)}>关闭</Button>}>
        {report && (
          <>
            <Space size={12} style={{ marginBottom: 12 }} wrap>
              <span style={{ fontSize: 12, color: T.steel }}>
                {report.report_kind === 'weekly'
                  ? `${report.week_start ? dayjs(report.week_start).format('MM/DD') : '—'} ~ ${dayjs(report.target_date).format('MM/DD')}`
                  : dayjs(report.target_date).format('YYYY-MM-DD')}
              </span>
              <span style={{ fontSize: 12, color: T.steel }}>共 {report.total} 条报警</span>
              <span style={{ fontSize: 12, color: T.steel }}>AI 分析 {report.analyzed}/{report.total} 条</span>
              {report.push_results.map((r, i) => {
                const cfg = r.success ? PUSH_RESULT.success : r.skipped ? PUSH_RESULT.skipped : PUSH_RESULT.failed
                return (
                  <Tooltip key={i} title={r.error || r.reason || undefined}>
                    <Tag color={cfg.color}>{cfg.label}</Tag>
                  </Tooltip>
                )
              })}
            </Space>
            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: MONO_FONT, fontSize: 13, lineHeight: 1.8, margin: 0,
              background: '#fafafa', padding: 16, borderRadius: 8, maxHeight: '60vh', overflow: 'auto' }}>
              {report.markdown_report}
            </pre>
          </>
        )}
      </Modal>
    </div>
  )
}
