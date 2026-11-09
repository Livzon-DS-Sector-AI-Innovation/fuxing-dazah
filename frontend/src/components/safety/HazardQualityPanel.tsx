'use client'

// 隐患 AI 识别质量看板 Panel（P1-4）— 实时聚合只读（后端 quality_dashboard），
// 指标与离线 replay（hazard_ai_quality_replay）同口径同数据集时数字一致。
// 布局：窗口切换 + KPI 行 + P0-C 基线对照 + 双趋势图（调用/闸门、引用/占位）
// + 失败分类与修复阶段 + 检索维度（P1-1 多路观测）+ 死信水位。

import { useMemo, useState } from 'react'
import { Segmented, Table, Tabs } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import {
  fetchExceptionReviewDashboard,
  fetchHazardQualityDashboard,
} from '@/lib/api/safety/hazard-quality'
import type {
  ExceptionReviewItem,
  HazardDeadLetterItem,
  HazardQualityBaselineItem,
  HazardQualityDashboard,
} from '@/types/safety'
import {
  EmptyGuide,
  RankBarChart,
  SectionCard,
  StatCard,
  StatusTag,
  TrendAreaChart,
} from '@/components/ui-kit'

/** 闸门拒绝分类 → 中文标签（quality_gate category 值 + replay 的 json_invalid） */
const GATE_CATEGORY_LABELS: Record<string, string> = {
  json_invalid: 'JSON 无法解析',
  retrieval_degraded: '检索降级拦截',
  no_chunks: '检索零召回',
  empty_basis: '判定依据为空',
  placeholder_basis: '占位依据',
  no_citation: '依据不含法规引用',
  invalid_citation: '引用不可验证（C2）',
}

/** JSON 修复阶段 → 中文标签（json_repair stages） */
const REPAIR_STAGE_LABELS: Record<string, string> = {
  trailing_comma: '尾逗号',
  slice_object: '截取对象',
  fullwidth_quotes: '全角引号',
}

type WindowOption = 7 | 30

function fmtRate(rate: number | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return '—'
  return `${rate.toFixed(1)}%`
}

function fmtWhen(ts: number | null | undefined): string {
  if (!ts || !Number.isFinite(ts) || ts <= 0) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** 多路开启率：multi_query_calls / calls_with_meta（老审计行无检索字段不计分母） */
function multiQueryRate(d: HazardQualityDashboard | undefined): number | null {
  if (!d || d.retrieval.calls_with_meta <= 0) return null
  return (d.retrieval.multi_query_calls / d.retrieval.calls_with_meta) * 100
}

const BASELINE_COLUMNS: ColumnsType<HazardQualityBaselineItem> = [
  { title: '指标', dataIndex: 'metric', key: 'metric' },
  { title: 'P0-C 基线', dataIndex: 'baseline', key: 'baseline', width: 110, render: (v: number) => (v == null ? '—' : `${v}`) },
  { title: '当前窗口', dataIndex: 'current', key: 'current', width: 110 },
  {
    title: '硬底线',
    dataIndex: 'floor',
    key: 'floor',
    width: 90,
    render: (v: number | null) => (v == null ? '—' : `≥${v}`),
  },
  {
    title: '判定',
    dataIndex: 'ok',
    key: 'ok',
    width: 110,
    render: (ok: boolean | null) => {
      if (ok === null) return <StatusTag tone="default" label="窗口不同·不可比" />
      return ok ? (
        <StatusTag tone="ok" label="达标" />
      ) : (
        <StatusTag tone="danger" label="回退" />
      )
    },
  },
]

const DEAD_COLUMNS: ColumnsType<HazardDeadLetterItem> = [
  { title: '记录', dataIndex: 'record_id', key: 'record_id', ellipsis: true },
  { title: '失败次数', dataIndex: 'attempts', key: 'attempts', width: 90 },
  {
    title: '分类',
    dataIndex: 'category',
    key: 'category',
    width: 130,
    render: (v: string) => GATE_CATEGORY_LABELS[v] ?? v,
  },
  { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
  { title: '死信时间', dataIndex: 'dead_at', key: 'dead_at', width: 170, render: fmtWhen },
]

/** 例外标签 → 中文（exception_reviewer.ExceptionLabel 值） */
const EXCEPTION_LABELS: Record<string, string> = {
  rag_degraded: 'RAG 降级',
  no_chunks: '检索零召回',
  basis_missing: '依据空/占位',
  citation_unverified: '引用不可验证',
  json_invalid: 'JSON 持续非法',
  validation_failed: '校验失败',
  writeback_error: '写回失败',
  manual_pick: '人工指定',
  other: '其他',
}

/** 建议动作 → 中文（ProposedAction 值） */
const REVIEW_ACTION_LABELS: Record<string, string> = {
  adopt_ai: '建议采纳 AI',
  keep_manual: '维持人工',
  escalate: '分歧提请专审',
  insufficient: '证据不足',
}

function fmtIsoWhen(iso: string | undefined): string {
  if (!iso) return '—'
  const ts = Date.parse(iso)
  if (!Number.isFinite(ts)) return iso
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}

const REVIEW_COLUMNS: ColumnsType<ExceptionReviewItem> = [
  { title: '记录', dataIndex: 'record_id', key: 'record_id', ellipsis: true },
  {
    title: '例外类型',
    dataIndex: 'label',
    key: 'label',
    width: 120,
    render: (v: string) => EXCEPTION_LABELS[v] ?? v,
  },
  {
    title: '来源',
    dataIndex: 'source',
    key: 'source',
    width: 90,
    render: (v: string) => (v === 'dead_letter' ? '死信' : '点名'),
  },
  {
    title: 'rescued',
    dataIndex: 'rescued',
    key: 'rescued',
    width: 90,
    render: (v: boolean) =>
      v ? <StatusTag tone="ok" label="rescued" /> : <StatusTag tone="default" label="—" />,
  },
  {
    title: '建议动作',
    dataIndex: 'action',
    key: 'action',
    width: 120,
    render: (v: string) => REVIEW_ACTION_LABELS[v] ?? v,
  },
  { title: 'AI 新结论依据', dataIndex: 'ai_basis', key: 'ai_basis', ellipsis: true },
  {
    title: '复核时间',
    dataIndex: 'observed_at',
    key: 'observed_at',
    width: 170,
    render: (v: string) => fmtIsoWhen(v),
  },
]

/** 例外复核 Tab 内容（P1-3 observe：指标 + 复核清单；不写回口径） */
function ExceptionReviewTab({ days }: { days: WindowOption }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['hazard-exception-reviews', days],
    queryFn: () => fetchExceptionReviewDashboard(days),
    staleTime: 60_000,
  })
  const m = data?.metrics

  if (error) {
    return (
      <EmptyGuide
        title="例外复核数据加载失败"
        description={error instanceof Error ? error.message : String(error)}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="已分析条数（窗口）"
          value={m ? m.analyzed_count : '—'}
          loading={isLoading}
          sub="① 主链 AI 调用记录数"
        />
        <StatCard
          label="复核条数（窗口）"
          value={m ? m.reviewed : '—'}
          loading={isLoading}
          sub="被复核的例外记录"
        />
        <StatCard
          label="例外率"
          value={m ? fmtRate(m.exception_rate * 100) : '—'}
          tone="warn"
          loading={isLoading}
          sub="复核条数 / 已分析条数（P1 目标 <8%）"
        />
        <StatCard
          label="rescued 率"
          value={m ? fmtRate(m.rescued_rate * 100) : '—'}
          tone="ok"
          loading={isLoading}
          sub={`rescued ${m?.rescued ?? 0} / ${m?.reviewed ?? 0}（P1 目标 ≥60%）`}
        />
        <StatCard
          label="死信水位（当前）"
          value={data?.dead_letters.count == null ? '未知' : data.dead_letters.count}
          tone={
            data?.dead_letters.count == null
              ? 'warn'
              : data.dead_letters.count > 0
                ? 'danger'
                : 'ok'
          }
          loading={isLoading}
          sub="复核捞取的候补池"
        />
      </div>

      {!data?.reviews_available && (
        <EmptyGuide compact title="复核报告存储读取失败，指标按零降级" />
      )}

      <SectionCard title="复核清单（observe · 不写回，仅候选证据）">
        {data && data.items.length > 0 ? (
          <Table<ExceptionReviewItem>
            size="small"
            rowKey="record_id"
            columns={REVIEW_COLUMNS}
            dataSource={data.items}
            loading={isLoading}
            pagination={false}
          />
        ) : (
          <EmptyGuide
            compact
            title="窗口内暂无复核记录"
            description="安全管理员可 @安全AI助手 说「复核死信」触发（observe，不写回）"
          />
        )}
      </SectionCard>
    </div>
  )
}

export default function HazardQualityPanel() {
  const [days, setDays] = useState<WindowOption>(30)
  const { data, isLoading, error } = useQuery({
    queryKey: ['hazard-quality-dashboard', days],
    queryFn: () => fetchHazardQualityDashboard(days),
    staleTime: 60_000,
  })

  const daysSorted = useMemo(
    () => Object.keys(data?.by_day ?? {}).sort(),
    [data],
  )
  const trendCalls = daysSorted.map((d) => data?.by_day[d]?.calls ?? 0)
  const trendGate = daysSorted.map((d) => data?.by_day[d]?.gate_pass ?? 0)
  const trendCitation = daysSorted.map((d) => data?.by_day[d]?.citation_ok ?? 0)
  const trendPlaceholder = daysSorted.map(
    (d) => data?.by_day[d]?.placeholder_variant ?? 0,
  )

  const mqRate = multiQueryRate(data)
  const deadCount = data?.dead_letters.count

  if (error) {
    return (
      <EmptyGuide
        title="质量看板加载失败"
        description={error instanceof Error ? error.message : String(error)}
      />
    )
  }

  return (
    <div className="space-y-4">
      <Tabs
        defaultActiveKey="overview"
        items={[
          {
            key: 'overview',
            label: '总览',
            children: (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <Segmented
                    value={days}
                    onChange={(v) => setDays(v as WindowOption)}
                    options={[
                      { value: 30, label: '近 30 天' },
                      { value: 7, label: '近 7 天' },
                    ]}
                  />
                  <span className="text-xs text-neutral-500">
                    {data ? `${data.totals.calls} 次调用 · 实时聚合（与 replay 同口径）` : '实时聚合只读'}
                  </span>
                </div>

      {/* KPI 行：JSON/闸门/引用/占位 + 多路观测 + 死信水位 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="JSON 修复后合法率"
          value={data ? fmtRate(data.totals.json_valid_after_rate) : '—'}
          tone="ok"
          loading={isLoading}
          sub={data ? `修复救援 ${data.totals.repaired_recovered} 次` : undefined}
        />
        <StatCard
          label="闸门通过率"
          value={data ? fmtRate(data.totals.gate_pass_rate) : '—'}
          loading={isLoading}
          sub={data ? `通过 ${data.totals.gate_pass_calls} / 拒绝 ${data.totals.gate_fail_calls}` : undefined}
        />
        <StatCard
          label="引用单元可验证率"
          value={data ? fmtRate(data.citation.unit_verified_rate) : '—'}
          tone="ok"
          loading={isLoading}
          sub={data ? `硬底线 ≥95%（P0-C 基线 95.7%）` : undefined}
        />
        <StatCard
          label="占位变体率"
          value={data ? fmtRate(data.citation.placeholder_variant_rate) : '—'}
          tone="warn"
          loading={isLoading}
          sub={data ? `分母=有证据调用 ${data.citation.calls_with_evidence}` : undefined}
        />
        <StatCard
          label="多路开启率"
          value={mqRate == null ? '—' : fmtRate(mqRate)}
          loading={isLoading}
          sub={data ? `观测调用 ${data.retrieval.calls_with_meta} · rewrite 命中 ${data.retrieval.rewrite_hit_calls}` : undefined}
        />
        <StatCard
          label="死信水位"
          value={deadCount == null ? '未知' : deadCount}
          tone={deadCount == null ? 'warn' : deadCount > 0 ? 'danger' : 'ok'}
          loading={isLoading}
          sub={deadCount == null ? '账本读取失败' : deadCount > 0 ? '需要人工处置' : '无死信'}
        />
      </div>

      {/* P0-C 基线对照 */}
      <SectionCard title="P0-C 基线对照（30d 窗口同量才可比）">
        <Table<HazardQualityBaselineItem>
          size="small"
          rowKey="metric"
          columns={BASELINE_COLUMNS}
          dataSource={data?.baseline ?? []}
          loading={isLoading}
          pagination={false}
          locale={{ emptyText: '暂无数据' }}
        />
      </SectionCard>

      {/* 双趋势图 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SectionCard title="调用量与闸门通过（按日）">
          <TrendAreaChart
            dates={daysSorted}
            seriesA={trendCalls}
            seriesB={trendGate}
            labelA="调用量"
            labelB="闸门通过"
            toneA="primary"
            toneB="ok"
            emptyText="窗口内暂无调用"
          />
        </SectionCard>
        <SectionCard title="引用可验证与占位变体（按日）">
          <TrendAreaChart
            dates={daysSorted}
            seriesA={trendCitation}
            seriesB={trendPlaceholder}
            labelA="引用可验证调用"
            labelB="占位变体调用"
            toneA="ok"
            toneB="warn"
            emptyText="窗口内暂无调用"
          />
        </SectionCard>
      </div>

      {/* 失败分类 + 修复阶段 + 检索维度 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SectionCard title="闸门拒绝分类">
          {data && Object.keys(data.gate_categories).length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.gate_categories)
                .sort((a, b) => b[1] - a[1])
                .map(([category, count]) => (
                  <StatusTag
                    key={category}
                    tone="danger"
                    label={`${GATE_CATEGORY_LABELS[category] ?? category} · ${count}`}
                  />
                ))}
            </div>
          ) : (
            <EmptyGuide compact title="窗口内无拒绝调用" />
          )}
          {data && Object.keys(data.repair_stages).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(data.repair_stages).map(([stage, count]) => (
                <StatusTag
                  key={stage}
                  tone="info"
                  label={`修复·${REPAIR_STAGE_LABELS[stage] ?? stage} · ${count}`}
                />
              ))}
            </div>
          )}
        </SectionCard>
        <SectionCard title="检索维度（Top 命中文档）">
          <RankBarChart
            names={(data?.retrieval.top_docs ?? []).map(([name]) => name)}
            values={(data?.retrieval.top_docs ?? []).map(([, count]) => count)}
            emptyText="窗口内暂无检索维度审计（P1-1 前的调用无此字段）"
          />
        </SectionCard>
      </div>

        {/* 死信清单 */}
        <SectionCard title="死信清单（第 5 次失败进入，需人工处置）">
          {deadCount == null ? (
            <EmptyGuide compact title="死信账本读取失败，水位未知" />
          ) : data && data.dead_letters.items.length > 0 ? (
            <Table<HazardDeadLetterItem>
              size="small"
              rowKey="record_id"
              columns={DEAD_COLUMNS}
              dataSource={data.dead_letters.items}
              pagination={false}
            />
          ) : (
            <EmptyGuide compact title="当前无死信" />
          )}
        </SectionCard>
              </div>
            ),
          },
          {
            key: 'exception_reviews',
            label: '例外复核',
            children: <ExceptionReviewTab days={days} />,
          },
        ]}
      />
    </div>
  )
}
