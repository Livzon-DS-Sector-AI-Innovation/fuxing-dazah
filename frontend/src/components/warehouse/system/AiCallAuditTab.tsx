'use client'

// AI 调用审计 Tab：GET /warehouse/ai-audits 分页表 + 顶部统计卡（/ai-audits/stats）
// 筛选：场景（agent_chat/receipt_recognition）/ 状态（success/failed）/ trace_id 搜索；
// 行点击 → 详情抽屉（GET /warehouse/ai-audits/{id}，输入/输出 JSON 全文）。

import { useCallback, useEffect, useState } from 'react'
import { Alert, App, Button, Empty, Input, Select, Skeleton, Space, Table } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import {
  getWarehouseAiAuditDetail,
  getWarehouseAiAuditStats,
  getWarehouseAiAudits,
} from '@/actions/warehouse'
import type {
  WarehouseAiAuditListItem,
  WarehouseAiAuditStats,
} from '@/types/warehouse'
import AiCallAuditDrawer from './AiCallAuditDrawer'
import {
  CARD_STYLE,
  MONO_FONT,
  UI,
  formatLatency,
  formatNumber,
  formatTime,
  formatTokens,
  scenarioLabel,
} from './systemConfigConstants'

const SCENARIO_OPTIONS = [
  { value: 'agent_chat', label: '仓库助手对话' },
  { value: 'receipt_recognition', label: '送货单识别入库' },
]

const STATUS_OPTIONS = [
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

const PAGE_SIZE = 20

/** 统计卡（自绘，字段缺省兜底「—」） */
function KpiCard({
  label,
  value,
  caption,
  valueColor,
  bg,
}: {
  label: string
  value: string
  caption?: string
  valueColor?: string
  bg?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 130, padding: '12px 14px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.steel }}>{label}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          lineHeight: 1.3,
          marginTop: 4,
          color: valueColor ?? UI.ink,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: UI.steel, marginTop: 2, minHeight: 16 }}>{caption ?? ''}</div>
    </div>
  )
}

export default function AiCallAuditTab() {
  const { message } = App.useApp()

  // 列表
  const [rows, setRows] = useState<WarehouseAiAuditListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  // 筛选
  const [scenario, setScenario] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [traceId, setTraceId] = useState('')

  // 统计
  const [stats, setStats] = useState<WarehouseAiAuditStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  // 详情抽屉
  const [detail, setDetail] = useState<WarehouseAiAuditListItem | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadList = useCallback(
    async (p: number, ps: number) => {
      setLoading(true)
      setListError(null)
      try {
        const res = await getWarehouseAiAudits({
          scenario,
          status,
          trace_id: traceId.trim() || undefined,
          page: p,
          page_size: ps,
        })
        setRows(res.items)
        setTotal(res.total)
      } catch (e) {
        setListError(e instanceof Error ? e.message : '查询审计记录失败')
      } finally {
        setLoading(false)
      }
    },
    [scenario, status, traceId],
  )

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const data = await getWarehouseAiAuditStats({ days: 7 })
      setStats(data)
    } catch {
      // 统计失败不阻断列表（卡片显示 —）
      setStats(null)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  // 筛选变化即查（对齐 warehouse StockTable 的 setTimeout 派发，规避 effect 内同步 setState）
  useEffect(() => {
    const t = setTimeout(() => {
      setPage(1)
      void loadList(1, pageSize)
      void loadStats()
    }, 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, status])

  const refresh = () => {
    void loadList(page, pageSize)
    void loadStats()
  }

  const openDetail = async (row: WarehouseAiAuditListItem) => {
    setDetailOpen(true)
    setDetailLoading(true)
    try {
      const data = await getWarehouseAiAuditDetail(row.id)
      setDetail(data)
    } catch (e) {
      // 详情失败回退列表行数据（列表已含 json 全文）
      setDetail(row)
      message.error(e instanceof Error ? e.message : '获取详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const totals = stats?.totals
  const successRate =
    totals && totals.calls > 0
      ? (((totals.calls - (totals.failed ?? 0)) / totals.calls) * 100).toFixed(1) + '%'
      : null
  const byScenario = stats?.by_scenario ?? []
  const weightedCalls = byScenario.reduce((a, s) => a + (s.calls ?? 0), 0)
  const avgLatencyMs = weightedCalls
    ? byScenario.reduce((a, s) => a + (s.avg_latency_ms ?? 0) * (s.calls ?? 0), 0) / weightedCalls
    : null

  const columns: ColumnsType<WarehouseAiAuditListItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v: string) => (
        <span style={{ fontSize: 12, color: UI.slate, whiteSpace: 'nowrap' }}>{formatTime(v)}</span>
      ),
    },
    {
      title: '场景',
      dataIndex: 'scenario',
      key: 'scenario',
      width: 130,
      render: (v: string) => (
        <span style={{ fontSize: 13, color: UI.ink }}>{scenarioLabel(v)}</span>
      ),
    },
    {
      title: '资源',
      dataIndex: 'resource',
      key: 'resource',
      width: 120,
      ellipsis: true,
      render: (v: string | null) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>{v ?? '—'}</span>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      width: 140,
      ellipsis: true,
      render: (v: string) => <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>{v}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (v: string) =>
        v === 'success' ? (
          <span style={{ color: UI.success, fontSize: 12, fontWeight: 600 }}>成功</span>
        ) : (
          <span style={{ color: UI.error, fontSize: 12, fontWeight: 600 }}>失败</span>
        ),
    },
    {
      title: '降级',
      dataIndex: 'degradation_level',
      key: 'degradation_level',
      width: 90,
      render: (v: string | null) =>
        v ? (
          <span style={{ color: UI.warning, fontSize: 12 }}>{v}</span>
        ) : (
          <span style={{ color: UI.muted, fontSize: 12 }}>—</span>
        ),
    },
    {
      title: '耗时',
      dataIndex: 'latency_ms',
      key: 'latency_ms',
      width: 80,
      render: (v: number | null) => (
        <span style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
          {formatLatency(v)}
        </span>
      ),
    },
    {
      title: 'Token（入/出）',
      key: 'tokens',
      width: 120,
      render: (_, r) => (
        <span style={{ fontSize: 12, color: UI.slate, fontVariantNumeric: 'tabular-nums' }}>
          {formatTokens(r.input_tokens)} / {formatTokens(r.output_tokens)}
        </span>
      ),
    },
    {
      title: 'trace',
      dataIndex: 'trace_id',
      key: 'trace_id',
      width: 90,
      render: (v: string | null) =>
        v ? (
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
            {v.slice(0, 6)}
          </span>
        ) : (
          <span style={{ color: UI.muted }}>—</span>
        ),
    },
  ]

  return (
    <div>
      {/* 失败行左侧红描边 + 行手型（对齐 safety AiAuditPanel） */}
      <style>{`
        .wh-audit-row-failed > td:first-child { box-shadow: inset 3px 0 0 ${UI.error}; }
      `}</style>

      {/* ── 统计卡 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <KpiCard label="总调用（近7天）" value={totals ? formatNumber(totals.calls) : '—'} />
        <KpiCard
          label="成功率"
          value={successRate ?? '—'}
          valueColor={successRate && parseFloat(successRate) < 95 ? UI.warning : undefined}
        />
        <KpiCard
          label="TOKEN 消耗"
          value={
            totals ? formatTokens((totals.input_tokens ?? 0) + (totals.output_tokens ?? 0)) : '—'
          }
          caption={
            totals
              ? `入 ${formatTokens(totals.input_tokens)} / 出 ${formatTokens(totals.output_tokens)}`
              : undefined
          }
        />
        <KpiCard label="平均耗时" value={avgLatencyMs != null ? formatLatency(Math.round(avgLatencyMs)) : '—'} />
        <KpiCard
          label="失败"
          value={totals ? formatNumber(totals.failed ?? 0) : '—'}
          valueColor={totals && (totals.failed ?? 0) > 0 ? UI.error : undefined}
          bg={totals && (totals.failed ?? 0) > 0 ? UI.roseTint : undefined}
          caption={statsLoading ? '统计加载中…' : undefined}
        />
      </div>

      {/* ── 记录卡 ── */}
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
              style={{ width: 160 }}
              options={SCENARIO_OPTIONS}
              value={scenario}
              onChange={(v) => setScenario(v || undefined)}
            />
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 100 }}
              options={STATUS_OPTIONS}
              value={status}
              onChange={(v) => setStatus(v || undefined)}
            />
            <Input.Search
              placeholder="trace_id 精确搜索"
              style={{ width: 260 }}
              value={traceId}
              allowClear
              onChange={(e) => setTraceId(e.target.value)}
              onSearch={() => {
                setPage(1)
                void loadList(1, pageSize)
              }}
            />
          </Space>
          <Space size={16}>
            <span style={{ fontSize: 12, color: UI.steel }}>共 {total} 条</span>
            <Button icon={<ReloadOutlined />} onClick={refresh} title="刷新" />
          </Space>
        </div>

        {loading && rows.length === 0 && !listError ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : listError ? (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>审计记录查询失败</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{listError}</span>}
            action={
              <Button size="small" onClick={() => void loadList(page, pageSize)}>
                重试
              </Button>
            }
          />
        ) : (
          <Table<WarehouseAiAuditListItem>
            rowKey="id"
            size="small"
            loading={loading}
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1120 }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计记录" />
              ),
            }}
            onRow={(record) => ({
              style: { cursor: 'pointer' },
              onClick: () => void openDetail(record),
            })}
            rowClassName={(r) => (r.status === 'failed' ? 'wh-audit-row-failed' : '')}
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
        )}
      </div>

      <AiCallAuditDrawer
        open={detailOpen}
        detail={detail}
        loading={detailLoading}
        onClose={() => {
          setDetailOpen(false)
          setDetail(null)
        }}
      />
    </div>
  )
}
