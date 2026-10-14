'use client'

// 全流程监督页（三期起步 + 四期 1-D 扩展）：
// ① 作业票审核记录查询——按日期查当日 8 类特殊作业票审核摘要（StatCard 5 指标）
//   + 违规明细表 + 审核速递原文；只读口径：无手动触发按钮（触发走定时任务与 bot）。
// ② Agent 定时任务运行中心——15 个定时任务的最近运行时间/成败/耗时/错误摘要
//   （scheduler_task_run_log append-only 留痕），零按钮只读。
// 布局为后续核验清单引擎留位（本期不做）。

import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, DatePicker, Skeleton, Table, Tag, Tooltip } from 'antd'
import { CalendarClock, RefreshCw, TicketCheck, TriangleAlert } from 'lucide-react'
import dayjs, { type Dayjs } from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import { MarkdownView } from '@/components/toolbox/MarkdownView'
import {
  fetchSchedulerJobRuns,
  type JobRunItem,
} from '@/lib/api/safety/job-runs'
import {
  fetchWorkTicketReview,
  type WorkTicketReviewData,
  type WorkTicketViolation,
} from '@/lib/api/safety/workticket-review'

/** 8 类标准作业票中文名（对齐后端 report_builder TICKET_TYPE_NAMES） */
const TICKET_TYPE_NAMES: Record<string, string> = {
  hot_work: '动火作业',
  confined_space: '受限空间作业',
  height_work: '高处作业',
  lifting: '吊装作业',
  temporary_electricity: '临时用电作业',
  excavation: '动土作业',
  road_breaking: '断路作业',
  blind_plate: '盲板抽堵作业',
}

/** key_times JSON → 可读文本（k: v 逐项；空对象/异常兜底 —） */
function keyTimesText(v: WorkTicketViolation['key_times']): string {
  if (!v || typeof v !== 'object' || Object.keys(v).length === 0) return '—'
  return Object.entries(v)
    .map(([k, val]) => `${k}: ${String(val)}`)
    .join('；')
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return dayjs(iso).format('YYYY-MM-DD HH:mm')
  } catch {
    return iso
  }
}

export default function SupervisionPage() {
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [data, setData] = useState<WorkTicketReviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Agent 任务运行中心（与日期查询解耦，常驻展示）──
  const [jobRuns, setJobRuns] = useState<JobRunItem[] | null>(null)
  const [jobRunsLoading, setJobRunsLoading] = useState(true)
  const [jobRunsError, setJobRunsError] = useState<string | null>(null)

  const loadJobRuns = useCallback(async () => {
    setJobRunsLoading(true)
    setJobRunsError(null)
    try {
      const res = await fetchSchedulerJobRuns()
      setJobRuns(res.jobs)
    } catch (e) {
      setJobRunsError(e instanceof Error ? e.message : '查询任务运行状态失败')
      setJobRuns(null)
    } finally {
      setJobRunsLoading(false)
    }
  }, [])

  const load = useCallback(async (d: Dayjs) => {
    setLoading(true)
    setNotFound(false)
    setError(null)
    try {
      const res = await fetchWorkTicketReview(d.format('YYYY-MM-DD'))
      if (res === null) {
        setNotFound(true)
        setData(null)
      } else {
        setData(res)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '查询作业票审核记录失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // 挂载查今天（setState 全部发生在异步续体中，react-hooks/set-state-in-effect）
  useEffect(() => {
    void load(dayjs())
  }, [load])

  useEffect(() => {
    void loadJobRuns()
  }, [loadJobRuns])

  const violationColumns: ColumnsType<WorkTicketViolation> = [
    {
      title: '票号',
      dataIndex: 'ticket_no',
      width: 150,
      render: (v: string) => (
        <span className="font-mono text-[12px] text-[var(--color-steel)]">{v || '—'}</span>
      ),
    },
    {
      title: '票型',
      dataIndex: 'ticket_type',
      width: 130,
      render: (v: string) => TICKET_TYPE_NAMES[v] ?? v ?? '—',
    },
    {
      title: '规则',
      key: 'rule',
      width: 170,
      render: (_, r) => (
        <span className="whitespace-nowrap">
          <span className="text-[13px]">{r.rule_name || r.rule_no}</span>
          <span className="ml-1.5 font-mono text-[12px] text-[var(--color-stone)]">{r.rule_no}</span>
        </span>
      ),
    },
    {
      title: '判定',
      dataIndex: 'not_applicable',
      width: 90,
      render: (na: boolean) =>
        na ? (
          <Tag className="m-0 rounded-md" color="default">
            不适用
          </Tag>
        ) : (
          <StatusTag tone="danger" label="违规" />
        ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      render: (v: string) => <span className="text-[13px]">{v || '—'}</span>,
    },
    {
      title: '关键时间点',
      dataIndex: 'key_times',
      width: 220,
      render: (v: WorkTicketViolation['key_times']) => {
        const text = keyTimesText(v)
        return text === '—' ? (
          <span className="text-[var(--color-stone)]">—</span>
        ) : (
          <Tooltip title={text}>
            <span className="block truncate text-[12px] text-[var(--color-steel)]">{text}</span>
          </Tooltip>
        )
      },
    },
  ]

  /** 任务耗时毫秒 → 可读文本 */
  function fmtDuration(ms: number | null): string {
    if (ms === null || ms === undefined) return '—'
    const seconds = ms / 1000
    if (seconds < 60) return `${seconds.toFixed(1)}s`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}分${String(Math.round(seconds % 60)).padStart(2, '0')}秒`
    return `${Math.floor(minutes / 60)}时${minutes % 60}分`
  }

  const jobRunColumns: ColumnsType<JobRunItem> = [
    {
      title: '任务',
      dataIndex: 'job_name',
      width: 170,
      render: (v: string, r) => (
        <Tooltip title={r.description || undefined} placement="topLeft">
          <span className="text-[13px]">{v}</span>
        </Tooltip>
      ),
    },
    {
      title: '计划时间',
      dataIndex: 'schedule_text',
      width: 110,
      render: (v: string) => (
        <span className="whitespace-nowrap text-[12px] text-[var(--color-steel)]">{v}</span>
      ),
    },
    {
      title: '最近运行',
      key: 'last_run_at',
      width: 140,
      render: (_, r) => (
        <span className="whitespace-nowrap text-[12px]">
          {r.last_run ? fmtDateTime(r.last_run.started_at) : '—'}
        </span>
      ),
    },
    {
      title: '结果',
      key: 'last_run_status',
      width: 84,
      render: (_, r) => {
        if (!r.last_run) return <StatusTag tone="default" label="未运行" />
        return r.last_run.status === 'success' ? (
          <StatusTag tone="ok" label="成功" />
        ) : (
          <StatusTag tone="danger" label="失败" />
        )
      },
    },
    {
      title: '耗时',
      key: 'duration',
      width: 90,
      render: (_, r) => (
        <span className="text-[12px] text-[var(--color-steel)]">
          {fmtDuration(r.last_run?.duration_ms ?? null)}
        </span>
      ),
    },
    {
      title: '错误摘要',
      key: 'error',
      ellipsis: true,
      render: (_, r) => {
        const err = r.last_run?.error
        if (!err) return <span className="text-[var(--color-stone)]">—</span>
        return (
          <Tooltip title={err}>
            <span className="block truncate text-[12px] text-[var(--color-danger, #c2410c)]">
              {err}
            </span>
          </Tooltip>
        )
      },
    },
  ]

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '全流程监督']}
        title="全流程监督"
        description="作业票审核记录查询：当日 8 类特殊作业票审核结果与违规明细（审核由每日 17:00 定时任务与机器人触发）"
        actions={
          <>
            <DatePicker
              value={date}
              allowClear={false}
              onChange={(d) => {
                const next = d ?? dayjs()
                setDate(next)
                void load(next)
              }}
              data-testid="supervision-date-picker"
            />
            <Button icon={<RefreshCw size={14} />} onClick={() => void load(date)} loading={loading}>
              刷新
            </Button>
          </>
        }
      />

      {loading ? (
        <div className="rounded-xl border border-[var(--color-hairline)] bg-white p-5">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message="作业票审核记录加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void load(date)}>
              重试
            </Button>
          }
        />
      ) : notFound ? (
        <div className="rounded-xl border border-[var(--color-hairline)] bg-white">
          <EmptyGuide
            icon={<TicketCheck size={22} />}
            title={`${date.format('YYYY-MM-DD')} 尚无作业票审核记录`}
            description="审核结果由每日 17:00 定时任务生成并推送飞书；当日任务未跑或当日无票时暂无记录，可稍后查询或切换日期查看历史。"
          />
        </div>
      ) : data ? (
        <div className="flex flex-col gap-4">
          {/* ── 审核摘要统计行 ── */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatCard
              label="当日作业票总数"
              value={data.total}
              sub="标准 8 类作业票"
              icon={<TicketCheck size={16} />}
            />
            <StatCard label="已审核" value={data.reviewed} sub="具备开始时间、纳入规则审核" />
            <StatCard
              label="违规票"
              value={data.violation_count}
              tone={data.violation_count > 0 ? 'danger' : 'default'}
              sub={data.violation_count > 0 ? '含违规条数的票数' : '全部合规'}
              icon={<TriangleAlert size={16} />}
            />
            <StatCard label="合格票" value={data.compliant_count} tone={data.compliant_count > 0 ? 'ok' : 'default'} />
            <StatCard label="数据不足" value={data.data_insufficient} sub="缺开始时间/关键字段" />
          </div>

          {/* ── 违规明细 ── */}
          <SectionCard
            title="违规明细"
            description={`逐票违规与不适用判定（共 ${data.violations.length} 条）`}
          >
            {data.violations.length === 0 ? (
              <EmptyGuide
                compact
                title="当日无违规票"
                description="全部通过规则审核，或违规明细未生成"
              />
            ) : (
              <Table<WorkTicketViolation>
                rowKey={(r) => r.id}
                size="small"
                columns={violationColumns}
                dataSource={data.violations}
                scroll={{ x: 1000 }}
                pagination={
                  data.violations.length > 10
                    ? { pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }
                    : false
                }
              />
            )}
          </SectionCard>

          {/* ── 审核速递原文（与飞书推送一致，含 8 类票分布） ── */}
          <SectionCard
            title="审核速递原文"
            description={`完成于 ${fmtDateTime(data.finished_at)} · ${
              data.pushed ? '已推送飞书' : '未推送'
            }`}
            action={
              data.status !== 'success' ? (
                <StatusTag
                  tone={data.status === 'failed' ? 'danger' : 'warn'}
                  label={data.status === 'failed' ? '审核失败' : data.status}
                />
              ) : undefined
            }
          >
            {data.report_markdown ? (
              <MarkdownView text={data.report_markdown} />
            ) : (
              <EmptyGuide compact title="无速递原文" description="该单审核未生成 Markdown 报告" />
            )}
          </SectionCard>
        </div>
      ) : null}

      {/* ── Agent 定时任务运行中心（常驻，与上方日期查询解耦；零按钮只读） ── */}
      <div className="mt-4">
        <SectionCard
          title="Agent 定时任务运行中心"
          description="安全模块全部定时任务的运行留痕（每次尝试一行：成功/失败/超时 · 耗时 · 错误摘要）"
          action={
            jobRunsError ? (
              <StatusTag tone="warn" label="加载失败" />
            ) : (
              <span className="inline-flex items-center gap-1 text-[12px] text-[var(--color-stone)]">
                <CalendarClock size={13} />
                {jobRunsLoading ? '加载中…' : `${jobRuns?.length ?? 0} 个任务`}
              </span>
            )
          }
        >
          {jobRunsError ? (
            <EmptyGuide
              compact
              icon={<TriangleAlert size={24} />}
              title="任务运行状态加载失败"
              description={jobRunsError}
            />
          ) : (
            <Table<JobRunItem>
              rowKey="job_name"
              size="small"
              columns={jobRunColumns}
              dataSource={jobRuns ?? []}
              loading={jobRunsLoading}
              scroll={{ x: 800 }}
              locale={{
                emptyText: <EmptyGuide compact title="暂无任务运行数据" description="调度器运行后将自动留痕" />,
              }}
              pagination={
                (jobRuns?.length ?? 0) > 10
                  ? { pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }
                  : false
              }
            />
          )}
        </SectionCard>
      </div>
    </div>
  )
}
