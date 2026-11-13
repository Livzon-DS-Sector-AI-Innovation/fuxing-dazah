'use client'

// R3 运维自愈观测 Panel（SuperAgent R3 二期）—— 工单列表 + 时间线回放抽屉 + retry。
// 范式对齐 HazardQualityPanel（ai-quality P1-4）：ui-kit 卡片 + antd Table + react-query；
// 时间线渲染后端 timeline 端点五段聚合（trigger→decision→input→effect→outbox）；
// retry/一键执行仅 admin 显示（后端 RequireAdmin 兜底，前端按角色隐藏）。

import { useMemo, useState } from 'react'
import {
  Button,
  Drawer,
  Input,
  message,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  extendOpsSelfhealWindow,
  fetchOpsSelfhealTickets,
  fetchOpsSelfhealTimeline,
  retryOpsSelfhealTicket,
} from '@/lib/api/safety/ops-selfheal'
import type {
  OpsSelfhealTicket,
  OpsSelfhealTimelineEvent,
} from '@/types/safety/ops-selfheal'
import { EmptyGuide, SectionCard, StatusTag } from '@/components/ui-kit'
import { usePermissionStore } from '@/stores/permission'

const { Text } = Typography

/** 阶段 → 色块（与后端 R3_STAGE_LABELS 同口径） */
const STAGE_META: Record<string, { color: string; label: string }> = {
  detected: { color: 'default', label: '已检出' },
  diagnosed: { color: 'processing', label: '已诊断' },
  repairing: { color: 'warning', label: '修复中' },
  verify_wait: { color: 'cyan', label: '待收口' },
  needs_human: { color: 'error', label: '需人工' },
  closed: { color: 'success', label: '已关闭' },
}

/** 根因分类 → 标签色 */
const RC_META: Record<string, string> = {
  upstream_outage: 'volcano',
  quota_exhausted: 'magenta',
  network: 'orange',
  config_error: 'gold',
  data_issue: 'purple',
  code_bug: 'red',
  unknown: 'default',
}

const RC_LABELS: Record<string, string> = {
  upstream_outage: '上游依赖断连',
  quota_exhausted: '配额/余额耗尽',
  network: '本机网络瞬断',
  config_error: '配置错误',
  data_issue: '数据问题',
  code_bug: '代码缺陷',
  unknown: '未能归因',
}

/** 信号类 → 中文名（对齐 cards._signal_title 简版） */
const SIGNAL_LABELS: Record<string, string> = {
  job_failed: '定时任务失败',
  job_recovered: '任务已恢复',
  job_missed: '漏审定局',
  rag_degraded: 'RAG 知识层故障',
  rag_recovered: 'RAG 已恢复',
  effects_parked: '副作用队列卡死',
  hazard_deadletter: '隐患 AI 死信积压',
  dep_recovered: '上游依赖恢复',
  ops_batch: '多组件故障聚合',
  ai_call_failed: 'AI 调用连续失败',
  push_failed: '推送失败',
  ragflow_batch_fail: 'RAG 引擎批量失败',
  feishu_event_failed: '飞书事件处理失败',
}

/** 时间线事件 kind → 展示名/色 */
const EVENT_META: Record<string, { color: string; label: string }> = {
  trigger: { color: 'blue', label: '信号' },
  decision: { color: 'geekblue', label: '研判' },
  input: { color: 'purple', label: '输入' },
  effect: { color: 'orange', label: '动作' },
  outbox: { color: 'green', label: '投递' },
}

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('zh-CN', { hour12: false })
}

/** 管理员判定（roles 含 admin 族即显操作按钮；后端 RequireAdmin 兜底） */
function useIsAdmin(): boolean {
  const roles = usePermissionStore((s) => s.roles)
  return useMemo(
    () => (roles || []).some((r) => /admin|super/i.test(r)),
    [roles],
  )
}

export default function OpsSelfhealPanel() {
  const isAdmin = useIsAdmin()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [stage, setStage] = useState<string | undefined>()
  const [signal, setSignal] = useState<string | undefined>()
  const [jobName, setJobName] = useState<string>('')
  const [detailId, setDetailId] = useState<string | null>(null)

  const ticketsQuery = useQuery({
    queryKey: ['ops-selfheal-tickets', page, stage, signal, jobName],
    queryFn: () =>
      fetchOpsSelfhealTickets({
        page,
        page_size: 20,
        stage: stage ?? null,
        signal: signal ?? null,
        job_name: jobName || null,
      }),
    refetchInterval: 30_000, // 30s 轻轮询（运维观测页）
  })

  const timelineQuery = useQuery({
    queryKey: ['ops-selfheal-timeline', detailId],
    queryFn: () => fetchOpsSelfhealTimeline(detailId as string),
    enabled: !!detailId,
  })

  const retryMutation = useMutation({
    mutationFn: (id: string) => retryOpsSelfhealTicket(id),
    onSuccess: () => {
      message.success('已重投诊断（下轮执行器收口核对）')
      void queryClient.invalidateQueries({ queryKey: ['ops-selfheal-tickets'] })
      if (detailId) {
        void queryClient.invalidateQueries({
          queryKey: ['ops-selfheal-timeline', detailId],
        })
      }
    },
    onError: () => message.error('重试失败（仅 open 工单可重试）'),
  })

  const extendMutation = useMutation({
    mutationFn: (id: string) => extendOpsSelfhealWindow(id),
    onSuccess: (data) => {
      message.success(
        `窗口已延长：${data.old_window} → ${data.new_window}（仅当日生效）`,
      )
      void queryClient.invalidateQueries({ queryKey: ['ops-selfheal-tickets'] })
    },
    onError: () => message.error('延长失败（该 job 当日已改过或工单非 open）'),
  })

  const rows = ticketsQuery.data?.data ?? []
  const total = ticketsQuery.data?.meta?.total ?? 0

  const columns: ColumnsType<OpsSelfhealTicket> = [
    {
      title: '工单',
      dataIndex: 'title',
      width: 280,
      render: (v: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ fontSize: 13 }}>{v}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{row.short_name}</Text>
        </Space>
      ),
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 100,
      render: (s: string) => {
        const meta = STAGE_META[s] ?? { color: 'default', label: s }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '信号',
      dataIndex: 'signal',
      width: 130,
      render: (s: string | null) =>
        s ? SIGNAL_LABELS[s] ?? s : '—',
    },
    {
      title: '根因',
      dataIndex: 'root_cause_class',
      width: 140,
      render: (rc: string | null, row) => {
        if (!rc) return <Tag>未诊断</Tag>
        return (
          <Tooltip title={row.reasoning}>
            <Tag color={RC_META[rc] ?? 'default'}>
              {RC_LABELS[rc] ?? rc}
              {row.confidence != null ? ` ${(row.confidence * 100).toFixed(0)}%` : ''}
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '对象',
      key: 'subject',
      width: 140,
      render: (_: unknown, row) => row.job_name ?? row.component ?? '—',
    },
    {
      title: '动作',
      dataIndex: 'executed',
      width: 150,
      render: (executed: string[], row) => {
        const items = executed.length
          ? executed
          : row.planned.length
            ? row.planned.map((x) => `${x}(待)`)
            : []
        return items.length ? items.join('、') : '—'
      },
    },
    {
      title: '时间',
      dataIndex: 'first_seen_at',
      width: 160,
      render: (v: string | null, row) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{fmtWhen(v ?? row.created_at)}</Text>
          {row.escalate_guidance ? (
            <Text type="danger" style={{ fontSize: 12 }}>⚠ 需人工</Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, row) => (
        <Space size={4}>
          <Button size="small" onClick={() => setDetailId(row.id)}>
            时间线
          </Button>
          {isAdmin && row.status === 'open' ? (
            <>
              <Button
                size="small"
                loading={retryMutation.isPending && retryMutation.variables === row.id}
                onClick={() => retryMutation.mutate(row.id)}
              >
                Retry
              </Button>
              {row.signal === 'job_failed' ? (
                <Tooltip title="延长该 job 当日补发窗口（处方值优先，默认 +2h，仅当日）">
                  <Button
                    size="small"
                    loading={extendMutation.isPending && extendMutation.variables === row.id}
                    onClick={() => extendMutation.mutate(row.id)}
                  >
                    延长窗口
                  </Button>
                </Tooltip>
              ) : null}
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  const events: OpsSelfhealTimelineEvent[] = timelineQuery.data?.events ?? []

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <SectionCard
        title="自愈工单"
        action={
          <Space wrap>
            <Select
              allowClear
              placeholder="阶段"
              style={{ width: 120 }}
              value={stage}
              onChange={(v) => { setStage(v); setPage(1) }}
              options={Object.entries(STAGE_META).map(([value, m]) => ({
                value, label: m.label,
              }))}
            />
            <Select
              allowClear
              showSearch
              placeholder="信号类型"
              style={{ width: 170 }}
              value={signal}
              onChange={(v) => { setSignal(v); setPage(1) }}
              options={Object.entries(SIGNAL_LABELS).map(([value, label]) => ({
                value, label,
              }))}
            />
            <Input
              allowClear
              placeholder="按任务名筛选"
              style={{ width: 180 }}
              value={jobName}
              onChange={(e) => { setJobName(e.target.value); setPage(1) }}
            />
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={ticketsQuery.isLoading}
          columns={columns}
          dataSource={rows}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            showTotal: (t) => `共 ${t} 单`,
            onChange: (p) => setPage(p),
          }}
          locale={{
            emptyText: (
              <EmptyGuide
                title="暂无自愈工单"
                description="系统故障信号将自动开单诊断；当前无 open/历史工单"
              />
            ),
          }}
        />
      </SectionCard>

      <Drawer
        title={timelineQuery.data?.ticket?.title ?? '工单时间线'}
        width={720}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        destroyOnClose
      >
        {timelineQuery.isLoading ? (
          <Text type="secondary">加载中…</Text>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {timelineQuery.data?.ticket ? (
              <SectionCard title="工单概况">
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Space wrap>
                    <StatusTag
                      tone={timelineQuery.data.ticket.stage === 'needs_human'
                        ? 'danger'
                        : timelineQuery.data.ticket.stage === 'closed'
                          ? 'ok'
                          : 'info'}
                      label={timelineQuery.data.ticket.stage_label}
                    />
                    {timelineQuery.data.ticket.root_cause_class ? (
                      <Tag color={RC_META[timelineQuery.data.ticket.root_cause_class] ?? 'default'}>
                        {RC_LABELS[timelineQuery.data.ticket.root_cause_class]}
                        {timelineQuery.data.ticket.confidence != null
                          ? ` ${(timelineQuery.data.ticket.confidence * 100).toFixed(0)}%`
                          : ''}
                      </Tag>
                    ) : null}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      修复 {timelineQuery.data.ticket.repair_rounds ?? 0} 轮
                    </Text>
                  </Space>
                  {timelineQuery.data.ticket.escalate_guidance ? (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      需人工：{timelineQuery.data.ticket.escalate_guidance}
                    </Text>
                  ) : null}
                  {timelineQuery.data.ticket.dep_endpoints?.length ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      监控端点：{timelineQuery.data.ticket.dep_endpoints.join('、')}
                    </Text>
                  ) : null}
                  {isAdmin && timelineQuery.data.ticket.status === 'open' ? (
                    <Space>
                      <Button
                        size="small"
                        onClick={() => retryMutation.mutate(timelineQuery.data!.ticket.id)}
                      >
                        重投诊断
                      </Button>
                      {timelineQuery.data.ticket.signal === 'job_failed' ? (
                        <Button
                          size="small"
                          onClick={() =>
                            extendMutation.mutate(timelineQuery.data!.ticket.id)
                          }
                        >
                          延长当日窗口
                        </Button>
                      ) : null}
                    </Space>
                  ) : null}
                </Space>
              </SectionCard>
            ) : null}

            <SectionCard title={`时间线（${events.length} 条）`}>
              {events.length === 0 ? (
                <Text type="secondary">无事件</Text>
              ) : (
                <div style={{ display: 'grid', gap: 8 }}>
                  {events.map((e, i) => {
                    const meta = EVENT_META[e.kind] ?? { color: 'default', label: e.kind }
                    return (
                      <div
                        key={i}
                        style={{
                          borderLeft: '2px solid var(--color-border, #e5e7eb)',
                          paddingLeft: 12,
                          display: 'grid',
                          gap: 2,
                        }}
                      >
                        <Space wrap size={8}>
                          <Tag color={meta.color}>{meta.label}</Tag>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {fmtWhen(e.at)}
                          </Text>
                          {e.signal ? (
                            <Text style={{ fontSize: 12 }}>
                              {SIGNAL_LABELS[e.signal] ?? e.signal}
                            </Text>
                          ) : null}
                          {e.outcome ? (
                            <Text style={{ fontSize: 12 }}>研判={e.outcome}</Text>
                          ) : null}
                          {e.action ? (
                            <Text style={{ fontSize: 12 }}>动作={e.action}</Text>
                          ) : null}
                          {e.status ? (
                            <Text style={{ fontSize: 12 }}>状态={e.status}</Text>
                          ) : null}
                          {e.input_kind ? (
                            <Text style={{ fontSize: 12 }}>类型={e.input_kind}</Text>
                          ) : null}
                        </Space>
                        {e.last_error ? (
                          <Text type="danger" style={{ fontSize: 12 }}>
                            错误：{e.last_error}
                          </Text>
                        ) : null}
                        {e.payload && Object.keys(e.payload).length ? (
                          <Text
                            type="secondary"
                            style={{ fontSize: 11, wordBreak: 'break-all' }}
                          >
                            {JSON.stringify(e.payload).slice(0, 300)}
                          </Text>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              )}
            </SectionCard>
          </div>
        )}
      </Drawer>
    </div>
  )
}
