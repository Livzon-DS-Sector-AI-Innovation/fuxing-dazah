'use client'

// 监护补贴统计 Tab — 只读查询面（DESIGN-监护补贴统计前端-特殊作业Tab与只读API-20261026）
// 选部门+年月 → 实时拉部门监护人台账计算（与 AI 助手/月报同口径）：
// 汇总卡（折算前/后双口径）→ 按监护人汇总表 → 明细分页表 → 待核对/跳过清单。
// 生成 Excel 等写动作不在 Web（留 AI 助手，月报已自动私发）。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DatePicker, Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'

import {
  fetchGuardianSubsidySummary,
  fetchSubsidySources,
} from '@/lib/api/safety/subsidy'
import type {
  GuardianSubsidySummary,
  SubsidyDetailRow,
  SubsidyGuardianSummaryRow,
  SubsidySourceDept,
} from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'

// 月份可选范围：三台账最早数据 2026-07 ~ 当月
const MIN_MONTH = '2026-07'
const DEPT_STORAGE_KEY = 'safety.subsidy.dept'

const UI = {
  slate: '#5d5b54',
  steel: '#787671',
}

function prevMonth(d: Dayjs): Dayjs {
  return d.subtract(1, 'month')
}

export default function SubsidyPanel() {
  const [sources, setSources] = useState<SubsidySourceDept[]>([])
  const [department, setDepartment] = useState<string>('')
  const [month, setMonth] = useState<Dayjs>(prevMonth(dayjs()))
  const [data, setData] = useState<GuardianSubsidySummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 部门清单 + 默认部门（localStorage 记忆 → 回退第一个台账部门，拍板点 C）
  useEffect(() => {
    let cancelled = false
    fetchSubsidySources()
      .then((list) => {
        if (cancelled || list.length === 0) return
        setSources(list)
        const remembered = localStorage.getItem(DEPT_STORAGE_KEY)
        const fallback = list.find((s) => s.department === remembered)?.department
          || list[0].department
        setDepartment(fallback)
      })
      .catch(() => setError('部门清单加载失败，请刷新重试'))
    return () => { cancelled = true }
  }, [])

  const query = useCallback(async (dept: string, m: Dayjs) => {
    if (!dept) return
    setLoading(true)
    setError('')
    try {
      const res = await fetchGuardianSubsidySummary(dept, m.year(), m.month() + 1)
      setData(res)
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e.message : '查询失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  // 部门/月份切换即查（防抖 300ms）
  useEffect(() => {
    if (!department) return
    localStorage.setItem(DEPT_STORAGE_KEY, department)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { void query(department, month) }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [department, month, query])

  const stats = data?.stats

  // ── 按监护人汇总列（空作业类型列隐藏，避免一排 0） ──
  const summaryColumns = useMemo<ColumnsType<SubsidyGuardianSummaryRow>>(() => {
    const typeCols: { key: keyof SubsidyGuardianSummaryRow; label: string }[] = [
      { key: 'hot_work', label: '动火' },
      { key: 'height_work', label: '登高' },
      { key: 'confined_space', label: '受限' },
      { key: 'temporary_electricity', label: '临时用电' },
      { key: 'blind_plate', label: '抽堵盲板' },
      { key: 'excavation', label: '动土' },
      { key: 'road_breaking', label: '断路' },
      { key: 'lifting', label: '吊装' },
    ]
    const used = new Set(
      typeCols.filter((c) => data?.summaries.some((s) => (s[c.key] as number) > 0)).map((c) => c.key),
    )
    return [
      { title: '监护人', dataIndex: 'guardian_name', key: 'name' },
      {
        title: '级别',
        dataIndex: 'guardian_level',
        key: 'level',
        render: (v: string) => (
          <StatusTag tone={v === 'B证' ? 'info' : 'primary'} label={v || '未登记'} />
        ),
      },
      ...typeCols.filter((c) => used.has(c.key)).map((c) => ({
        title: c.label,
        dataIndex: c.key,
        key: c.key,
        align: 'right' as const,
      })),
      {
        title: '合计（元）',
        dataIndex: 'total',
        key: 'total',
        align: 'right' as const,
        render: (v: number) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>,
      },
    ]
  }, [data])

  const detailColumns = useMemo<ColumnsType<SubsidyDetailRow>>(() => [
    { title: '监护人', dataIndex: 'guardian_name', key: 'name', width: 90 },
    { title: '类型', dataIndex: 'operation_type', key: 'type', width: 95 },
    { title: '级别', dataIndex: 'operation_level', key: 'level', width: 70 },
    { title: '行标识', dataIndex: 'ticket_no', key: 'ticket', width: 110 },
    {
      title: '开始', dataIndex: 'start_time', key: 'start', width: 140,
      render: (v: string) => v?.slice(5, 16).replace('T', ' '),
    },
    {
      title: '结束', dataIndex: 'end_time', key: 'end', width: 140,
      render: (v: string) => v?.slice(5, 16).replace('T', ' '),
    },
    {
      title: '实算时长(h)', dataIndex: 'adjusted_hours', key: 'hours', width: 100, align: 'right',
      render: (v: number) => v,
    },
    {
      title: '计费', key: 'billing', width: 110, align: 'right',
      render: (_, r) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', color: UI.slate }}>
          {r.billing_unit_label === '天' || r.billing_unit_label === '张'
            ? `1${r.billing_unit_label}×${r.unit_price}`
            : r.billing_unit_label === '次/块/罐'
              ? `1次×${r.unit_price}`
              : `${r.billing_units}×${r.unit_price}`}
        </span>
      ),
    },
    {
      title: '金额（元）', dataIndex: 'subsidy_amount', key: 'amount', width: 95, align: 'right',
      render: (v: number) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{v}</span>
      ),
    },
    {
      title: '备注', dataIndex: 'remark', key: 'remark', ellipsis: true,
      render: (v: string) => <span style={{ color: UI.steel, fontSize: 12 }}>{v}</span>,
    },
  ], [])

  return (
    <div className="flex flex-col gap-4">

      {/* ── 查询条件 ── */}
      <SectionCard title="监护补贴查询" description="级别以台账登记为准，未登级别暂按 A 证计入；提炼六部台账无级别列，全员待核对">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            style={{ minWidth: 180 }}
            placeholder="选择部门"
            value={department || undefined}
            options={sources.map((s) => ({ value: s.department, label: s.department }))}
            onChange={setDepartment}
          />
          <DatePicker
            picker="month"
            value={month}
            allowClear={false}
            disabledDate={(d) => d.isBefore(MIN_MONTH, 'month') || d.isAfter(dayjs(), 'month')}
            onChange={(v) => v && setMonth(v)}
          />
        </div>
      </SectionCard>

      {/* ── 汇总卡 ── */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard label="计入条数" value={stats.matched} />
          <StatCard label="监护人数" value={stats.guardians} />
          <StatCard
            label="补贴总额（折算后）"
            value={stats.adjusted_total}
            sub={stats.adjusted_total !== stats.total_amount
              ? `折算前 ${stats.total_amount} 元（B证×0.5）`
              : 'A 证全额，无 B 证折算'}
          />
          <StatCard
            label="待核对"
            value={stats.unmatched_people}
            sub={`未登级别 ${stats.unmatched} 条，暂按 A 证`}
            tone={stats.unmatched_people > 0 ? 'warn' : 'default'}
          />
          <StatCard
            label="跳过"
            value={stats.skipped}
            sub="缺时间/无法解析/重叠去重"
            tone={stats.skipped > 0 ? 'warn' : 'default'}
          />
        </div>
      )}

      {/* ── 错误 / 空数据 ── */}
      {error && (
        <EmptyGuide
          title="查询失败"
          description={`${error}；生成 Excel 请使用 AI 助手。`}
        />
      )}
      {!error && data && stats && stats.matched === 0 && (
        <EmptyGuide
          title="当月无可计入记录"
          description="台账该月无登记（或均被跳过/待核对）；生成 Excel 请使用 AI 助手。"
        />
      )}

      {/* ── 按监护人汇总 ── */}
      {data && data.summaries.length > 0 && (
        <SectionCard title="按监护人汇总（元）" description="各类作业补贴构成">
          <Table<SubsidyGuardianSummaryRow>
            size="small"
            rowKey="guardian_name"
            columns={summaryColumns}
            dataSource={data.summaries}
            pagination={false}
          />
        </SectionCard>
      )}

      {/* ── 明细 ── */}
      {data && data.details.length > 0 && (
        <SectionCard title="明细记录" description="行标识=「MM-DD 姓名」（台账无票号）；金额为折算前">
          <Table<SubsidyDetailRow>
            size="small"
            rowKey={(r) => `${r.ticket_no}-${r.operation_type}`}
            columns={detailColumns}
            dataSource={data.details}
            loading={loading}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 1000 }}
          />
        </SectionCard>
      )}

      {/* ── 待核对与跳过 ── */}
      {data && (data.unmatched.length > 0 || data.skipped.length > 0) && (
        <SectionCard title="待核对与跳过" description="修正请直接改部门监护人台账，次日生效">
          {data.unmatched.length > 0 && (
            <div className="mb-3 flex flex-col gap-2">
              {data.unmatched.map((u) => (
                <div key={u.name} className="flex items-center gap-2">
                  <StatusTag tone="warn" label="待核对" />
                  <span>{u.name}</span>
                  <span style={{ color: UI.slate, fontSize: 12 }}>
                    {u.ticket_count} 行未登级别（暂按 A 证计入）· {u.operation_types.join('、')}
                  </span>
                </div>
              ))}
            </div>
          )}
          {data.skipped.length > 0 && (
            <div className="flex flex-col gap-2">
              {data.skipped.map((s) => (
                <div key={`${s.ticket_no}-${s.reason}`} className="flex items-center gap-2">
                  <StatusTag label="跳过" />
                  <span style={{ fontVariantNumeric: 'tabular-nums' }}>{s.ticket_no}</span>
                  <span style={{ color: UI.slate, fontSize: 12 }}>
                    {s.ticket_type} · {s.reason}
                  </span>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      )}
    </div>
  )
}
