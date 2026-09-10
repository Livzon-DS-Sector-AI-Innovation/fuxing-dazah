'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Empty,
  Input,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tooltip,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { Column } from '@ant-design/charts'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { getAiAuditStats, getAiCallAudit, listAiCallAudits } from '@/actions/safety'
import type { AiAuditStats, AiCallAuditDetail, AiCallAuditListItem } from '@/types/safety'
import AiAuditDetailDrawer from './AiAuditDetailDrawer'
import {
  CHANNEL_UI,
  ChannelTag,
  MONO_FONT,
  SCENARIO_UI,
  ScenarioTag,
  StatusDot,
  UI,
  absoluteTime,
  cacheHitRate,
  formatCacheRate,
  formatLatency,
  formatTokensAbbrev,
  latencyColor,
  relativeTime,
  scenarioUi,
} from './aiAuditConstants'

const SCENARIO_OPTIONS = Object.entries(SCENARIO_UI).map(([value, ui]) => ({
  value,
  label: ui.label,
}))

const STATUS_OPTIONS = [
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

const CHANNEL_OPTIONS = Object.entries(CHANNEL_UI).map(([value, ui]) => ({
  value,
  label: ui.label,
}))

type RangeKey = '1' | '7' | '30' | 'custom'

const RANGE_OPTIONS = [
  { label: '今天', value: '1' },
  { label: '近7天', value: '7' },
  { label: '近30天', value: '30' },
  { label: '自定义', value: 'custom' },
]

/** 表格行：trace 聚合模式下父行携带 children + traceCount */
type AuditRow = AiCallAuditListItem & { children?: AuditRow[]; traceCount?: number }

const CARD_STYLE: React.CSSProperties = {
  background: UI.canvas,
  border: `1px solid ${UI.hairline}`,
  borderRadius: 12,
}

// ── KPI 卡（自绘，非 antd Statistic，完全对齐 DESIGN.md） ──
function KpiCard({
  label,
  value,
  caption,
  valueColor,
  bg,
  onClick,
}: {
  label: string
  value: string
  caption?: string
  valueColor?: string
  bg?: string
  onClick?: () => void
}) {
  return (
    <div
      style={{
        ...CARD_STYLE,
        flex: 1,
        minWidth: 0,
        padding: '14px 16px',
        background: bg ?? UI.canvas,
        cursor: onClick ? 'pointer' : undefined,
      }}
      onClick={onClick}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: 1,
          color: UI.stone,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 600,
          lineHeight: 1.3,
          marginTop: 4,
          color: valueColor ?? UI.ink,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>
        {caption ?? ''}
      </div>
    </div>
  )
}

export default function AiAuditPanel() {
  const { message } = App.useApp()

  // ── 时间窗（全页联动：KPI + 趋势图 + 表格） ──
  const [rangeKey, setRangeKey] = useState<RangeKey>('7')
  const [customRange, setCustomRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)

  // ── 筛选 ──
  const [scenario, setScenario] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [channel, setChannel] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // ── 列表 ──
  const [rows, setRows] = useState<AiCallAuditListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)

  // ── 统计 ──
  const [stats, setStats] = useState<AiAuditStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  // ── trace 聚合（M3） ──
  const [traceGrouped, setTraceGrouped] = useState(false)

  // ── 详情抽屉 ──
  const [detail, setDetail] = useState<AiCallAuditDetail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailIndex, setDetailIndex] = useState(-1)

  const windowOf = useCallback((): { dateFrom?: string; dateTo?: string } => {
    const now = dayjs()
    if (rangeKey === '1') return { dateFrom: now.startOf('day').toISOString(), dateTo: now.endOf('day').toISOString() }
    if (rangeKey === '7') return { dateFrom: now.subtract(7, 'day').toISOString(), dateTo: now.endOf('day').toISOString() }
    if (rangeKey === '30') return { dateFrom: now.subtract(30, 'day').toISOString(), dateTo: now.endOf('day').toISOString() }
    return {
      dateFrom: customRange?.[0]?.startOf('day').toISOString(),
      dateTo: customRange?.[1]?.endOf('day').toISOString(),
    }
  }, [rangeKey, customRange])

  const loadList = useCallback(
    async (p: number, ps: number) => {
      setLoading(true)
      try {
        const { dateFrom, dateTo } = windowOf()
        const res = await listAiCallAudits({
          scenario,
          status,
          channel,
          keyword: keyword.trim() || undefined,
          date_from: dateFrom,
          date_to: dateTo,
          page: p,
          page_size: ps,
        })
        if (res.code >= 200 && res.code < 300 && res.data) {
          setRows(res.data)
          setTotal(res.meta?.total ?? 0)
        } else {
          message.error(res.message || '查询审计记录失败')
        }
      } finally {
        setLoading(false)
      }
    },
    [scenario, status, channel, keyword, windowOf, message],
  )

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const { dateFrom, dateTo } = windowOf()
      const res = await getAiAuditStats({ date_from: dateFrom, date_to: dateTo })
      if (res.code >= 200 && res.code < 300 && res.data) {
        setStats(res.data)
      }
    } finally {
      setStatsLoading(false)
    }
  }, [windowOf])

  // 筛选/时间窗变化即查（对齐 Helicone 的 filter-on-change）
  useEffect(() => {
    setPage(1)
    void loadList(1, pageSize)
    void loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, status, channel, rangeKey, customRange])

  const refresh = () => {
    void loadList(page, pageSize)
    void loadStats()
  }

  const searchByKeyword = () => {
    setPage(1)
    void loadList(1, pageSize)
  }

  // ── KPI 派生指标 ──
  const totals = stats?.totals
  const prev = stats?.prev_totals
  const successRate =
    totals && totals.calls > 0
      ? ((totals.calls - totals.failed) / totals.calls) * 100
      : null
  const callsDelta =
    totals && prev && prev.calls > 0
      ? Math.round(((totals.calls - prev.calls) / prev.calls) * 100)
      : null
  const byScenario = stats?.by_scenario ?? []
  const weightedCalls = byScenario.reduce((a, s) => a + s.calls, 0)
  const avgLatencyMs = weightedCalls
    ? byScenario.reduce((a, s) => a + s.avg_latency_ms * s.calls, 0) / weightedCalls
    : null
  const slowest = [...byScenario]
    .filter((s) => s.calls > 0)
    .sort((a, b) => b.avg_latency_ms - a.avg_latency_ms)[0]

  // ── 趋势图数据（场景中文名 + 固定色序） ──
  const chartData = useMemo(
    () =>
      (stats?.daily ?? []).map((d) => ({
        ...d,
        scenarioLabel: scenarioUi(d.scenario).label,
      })),
    [stats],
  )
  const chartConfig = {
    data: chartData,
    xField: 'date',
    yField: 'calls',
    colorField: 'scenarioLabel',
    stack: true,
    scale: {
      color: {
        domain: Object.values(SCENARIO_UI).map((u) => u.label),
        range: Object.values(SCENARIO_UI).map((u) => u.chart),
      },
      y: { domainMin: 0 },
    },
    axis: {
      y: {
        labelStyle: { fill: UI.stone, fontSize: 11 },
        grid: { stroke: UI.hairlineSoft, lineWidth: 0.5 },
      },
      x: {
        labelStyle: { fill: UI.stone, fontSize: 11 },
        line: { stroke: UI.hairlineSoft },
      },
    },
    legend: {
      position: 'top' as const,
      itemLabelFill: UI.slate,
      itemLabelFontSize: 12,
    },
    interaction: { tooltip: { marker: false } },
    style: { view: { fill: 'transparent' } },
  }

  // ── trace 聚合（仅当前页内分组；同 trace 的行创建时间相邻，通常同页） ──
  const displayRows: AuditRow[] = useMemo(() => {
    if (!traceGrouped) return rows
    const parents = new Map<string, AuditRow>()
    const out: AuditRow[] = []
    for (const r of rows) {
      if (!r.trace_id) {
        out.push({ ...r })
        continue
      }
      const parent = parents.get(r.trace_id)
      if (!parent) {
        const p: AuditRow = { ...r, traceCount: 1 }
        parents.set(r.trace_id, p)
        out.push(p)
      } else {
        parent.children = parent.children ?? []
        parent.children.push({ ...r })
        parent.traceCount = (parent.traceCount ?? 1) + 1
      }
    }
    return out
  }, [rows, traceGrouped])

  // 展示顺序拍平（供抽屉 上一条/下一条 导航）
  const flatRows = useMemo(() => {
    const acc: AiCallAuditListItem[] = []
    for (const r of displayRows) {
      acc.push(r)
      r.children?.forEach((c) => acc.push(c))
    }
    return acc
  }, [displayRows])

  const openDetailAt = useCallback(
    async (idx: number) => {
      const row = flatRows[idx]
      if (!row) return
      const res = await getAiCallAudit(row.id)
      if (res.code >= 200 && res.code < 300 && res.data) {
        setDetail(res.data)
        setDetailIndex(idx)
        setDetailOpen(true)
      } else {
        message.error(res.message || '获取详情失败')
      }
    },
    [flatRows, message],
  )

  const columns: ColumnsType<AuditRow> = [
    {
      title: '',
      dataIndex: 'status',
      width: 48,
      render: (v: string, r) => (
        <StatusDot status={v} degradationLevel={r.degradation_level} />
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => (
        <Tooltip title={absoluteTime(v)}>
          <span style={{ fontSize: 12, color: UI.slate, whiteSpace: 'nowrap' }}>
            {relativeTime(v)}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '场景',
      dataIndex: 'scenario',
      width: 110,
      render: (v: string) => <ScenarioTag scenario={v} />,
    },
    {
      title: '输入预览',
      dataIndex: 'input_preview',
      ellipsis: true,
      render: (v: string | null) => (
        <span style={{ fontSize: 13, color: UI.ink }}>{v ?? '—'}</span>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model',
      width: 130,
      ellipsis: true,
      render: (v: string) => <span style={{ fontSize: 12, color: UI.steel }}>{v}</span>,
    },
    {
      title: 'Token',
      key: 'tokens',
      width: 100,
      render: (_: unknown, r) => {
        const rate = formatCacheRate(r.cache_hit_tokens, r.cache_miss_tokens)
        return (
          <Tooltip title={`前缀缓存命中率: ${rate}`}>
            <span
              style={{ fontSize: 12, color: UI.slate, fontVariantNumeric: 'tabular-nums' }}
            >
              {formatTokensAbbrev(r.input_tokens)} / {formatTokensAbbrev(r.output_tokens)}
            </span>
          </Tooltip>
        )
      },
    },
    {
      title: '耗时',
      dataIndex: 'latency_ms',
      width: 72,
      render: (v: number | null) => (
        <span
          style={{
            fontSize: 12,
            color: latencyColor(v) ?? UI.slate,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {formatLatency(v)}
        </span>
      ),
    },
    {
      title: '用户',
      dataIndex: 'user_name',
      width: 80,
      render: (v: string | null) => (
        <span style={{ fontSize: 12, color: UI.slate }}>{v ?? '—'}</span>
      ),
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 72,
      render: (v: string | null) => <ChannelTag channel={v} />,
    },
    {
      title: 'trace',
      dataIndex: 'trace_id',
      width: 100,
      render: (v: string | null, r) =>
        v ? (
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
            {v.slice(0, 6)}
            {traceGrouped && (r.traceCount ?? 1) > 1 && (
              <span
                style={{
                  marginLeft: 6,
                  background: UI.grayTint,
                  color: UI.slate,
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '0 6px',
                  borderRadius: 9999,
                }}
              >
                ×{r.traceCount}
              </span>
            )}
          </span>
        ) : (
          <span style={{ color: UI.stone }}>—</span>
        ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* 失败行左侧红描边 + 行手型 */}
      <style>{`
        .ai-audit-table .ant-table-tbody > tr > td { cursor: pointer; }
        .ai-audit-row-failed > td:first-child { box-shadow: inset 3px 0 0 ${UI.error}; }
      `}</style>

      {/* ── A 页头 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>AI 调用审计</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            AI 系统的调用留痕与合规审计
          </div>
        </div>
        <Space>
          <Segmented
            options={RANGE_OPTIONS}
            value={rangeKey}
            onChange={(v) => setRangeKey(v as RangeKey)}
          />
          {rangeKey === 'custom' && (
            <DatePicker.RangePicker value={customRange} onChange={(v) => setCustomRange(v)} />
          )}
          <Button icon={<ReloadOutlined />} onClick={refresh} title="刷新" />
        </Space>
      </div>

      {/* ── B KPI 指标带 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <KpiCard
          label="总调用"
          value={totals ? totals.calls.toLocaleString() : '—'}
          caption={callsDelta != null ? `较上周期 ${callsDelta >= 0 ? '↑' : '↓'}${Math.abs(callsDelta)}%` : undefined}
        />
        <KpiCard
          label="成功率"
          value={successRate != null ? `${successRate.toFixed(1)}%` : '—'}
          valueColor={successRate != null && successRate < 95 ? UI.warning : undefined}
        />
        <KpiCard
          label="TOKEN 消耗"
          value={
            totals ? formatTokensAbbrev(totals.input_tokens + totals.output_tokens) : '—'
          }
          caption={
            totals
              ? `入 ${formatTokensAbbrev(totals.input_tokens)} / 出 ${formatTokensAbbrev(totals.output_tokens)}`
              : undefined
          }
        />
        <KpiCard
          label="平均耗时"
          value={avgLatencyMs != null ? formatLatency(avgLatencyMs) : '—'}
          caption={
            slowest
              ? `最慢：${scenarioUi(slowest.scenario).label} ${formatLatency(slowest.avg_latency_ms)}`
              : undefined
          }
        />
        <KpiCard
          label="前缀缓存命中率"
          value={formatCacheRate(totals?.cache_hit_tokens, totals?.cache_miss_tokens)}
          valueColor={
            (totals?.cache_hit_tokens ?? 0) + (totals?.cache_miss_tokens ?? 0) > 0
              ? (cacheHitRate(totals!.cache_hit_tokens, totals!.cache_miss_tokens) ?? 0) < 0.3
                ? UI.warning
                : UI.success
              : undefined
          }
          caption={
            totals
              ? `命中 ${formatTokensAbbrev(totals.cache_hit_tokens)} / 未命中 ${formatTokensAbbrev(totals.cache_miss_tokens)}`
              : undefined
          }
        />
        <KpiCard
          label="失败"
          value={totals ? String(totals.failed) : '—'}
          valueColor={totals && totals.failed > 0 ? UI.error : undefined}
          bg={totals && totals.failed > 0 ? UI.roseTint : undefined}
          caption={totals && totals.failed > 0 ? '点击筛选失败记录' : undefined}
          onClick={
            totals && totals.failed > 0 ? () => setStatus('failed') : undefined
          }
        />
      </div>

      {/* ── C 趋势图 ── */}
      {/* 注意：不给 Column 传 loading —— @ant-design/charts v2 在 loading 切换重挂载时
          会对同一容器重复 attachShadow 导致崩溃；loading 期间直接不渲染图表（与 energy 模块一致） */}
      <div style={{ ...CARD_STYLE, padding: '16px 20px', marginBottom: 16 }}>
        {chartData.length > 0 ? (
          <Column {...chartConfig} height={220} />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={statsLoading ? '加载中…' : '时间窗内暂无调用'}
            style={{ margin: '48px 0' }}
          />
        )}
      </div>

      {/* ── D+E 记录卡（筛选栏并入卡头） ── */}
      <div style={{ ...CARD_STYLE, padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
            marginBottom: 12,
          }}
        >
          <Space wrap>
            <Select
              allowClear
              placeholder="场景"
              style={{ width: 140 }}
              options={SCENARIO_OPTIONS}
              value={scenario}
              onChange={setScenario}
            />
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 100 }}
              options={STATUS_OPTIONS}
              value={status}
              onChange={setStatus}
            />
            <Select
              allowClear
              placeholder="渠道"
              style={{ width: 100 }}
              options={CHANNEL_OPTIONS}
              value={channel}
              onChange={setChannel}
            />
            <Input.Search
              placeholder="输入/输出关键字"
              style={{ width: 220 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onSearch={searchByKeyword}
              allowClear
            />
          </Space>
          <Space size={16}>
            <span style={{ fontSize: 12, color: UI.steel }}>共 {total} 条</span>
            <Space size={6}>
              <Switch
                size="small"
                checked={traceGrouped}
                onChange={setTraceGrouped}
              />
              <span style={{ fontSize: 12, color: UI.slate }}>按 trace 聚合</span>
            </Space>
          </Space>
        </div>

        <Table<AuditRow>
          className="ai-audit-table"
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={displayRows}
          scroll={{ x: 1180 }}
          expandable={{ indentSize: 12 }}
          rowClassName={(r) => (r.status === 'failed' ? 'ai-audit-row-failed' : '')}
          onRow={(record) => ({
            onClick: (e) => {
              // 展开图标的点击不打开详情
              if ((e.target as HTMLElement).closest('.ant-table-row-expand-icon')) return
              const idx = flatRows.findIndex((r) => r.id === record.id)
              if (idx >= 0) void openDetailAt(idx)
            },
          })}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
              void loadList(p, ps)
            },
          }}
        />
      </div>

      {/* ── F 详情抽屉 ── */}
      <AiAuditDetailDrawer
        open={detailOpen}
        detail={detail}
        onClose={() => setDetailOpen(false)}
        hasPrev={detailIndex > 0}
        hasNext={detailIndex >= 0 && detailIndex < flatRows.length - 1}
        onPrev={() => void openDetailAt(detailIndex - 1)}
        onNext={() => void openDetailAt(detailIndex + 1)}
      />
    </div>
  )
}
