'use client'

/**
 * 特种设备监控面板（facilities-p2 票 01/04）——「锅炉群消息 → 快照 → 展示 →
 * 处置闭环」的 Web 端入口。
 *
 * 四块：实时读数卡（票 01）+ 趋势图（票 01）+ 报警列表（票 04：ack/resolve
 * 处置操作与留痕展示）+ 待补录列表（票 04：原文摘录 + 人工补录确认）。
 * 空态兜底：采集未配置/尚无读数时给引导文案，不报错。
 */
import { useMemo, useState } from 'react'
import { Button, Empty, Input, Modal, Popconfirm, Radio, Select, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import {
  ackTelemetryAlarm,
  confirmTelemetryPendingReview,
  fetchTelemetryAlarms,
  fetchTelemetryHistory,
  fetchTelemetryLatest,
  fetchTelemetryPendingReviews,
  resolveTelemetryAlarm,
} from '@/lib/api/safety/telemetry'
import type {
  TelemetryAlarm,
  TelemetryLatestData,
  TelemetryLatestItem,
  TelemetryPendingReview,
} from '@/types/safety/telemetry'
import { EmptyGuide, SectionCard, SingleTrendChart, StatusTag } from '@/components/ui-kit'

const PARSE_LABEL: Record<string, string> = {
  template: '模板',
  ai: 'AI',
  manual: '人工',
}

/** 读数状态色（后端按当前生效规则对单点最新值的越界着色） */
const STATUS_COLOR: Record<string, string> = {
  normal: '#3f8f6f',
  warning: '#d9822b',
  alarm: '#e2585d',
}

function fmtTime(iso: string): string {
  return iso ? iso.slice(5, 16).replace('T', ' ') : '—'
}

function groupByEquipment(items: TelemetryLatestItem[]): Map<string, TelemetryLatestItem[]> {
  const map = new Map<string, TelemetryLatestItem[]>()
  for (const it of items) {
    const list = map.get(it.equipment_no) ?? []
    list.push(it)
    map.set(it.equipment_no, list)
  }
  return map
}

function ReadingsCard({ query }: { query: ReturnType<typeof useQuery<TelemetryLatestData>> }) {
  const items = query.data?.items ?? []
  const byEquipment = useMemo(() => groupByEquipment(items), [items])

  if (query.isLoading) {
    return (
      <SectionCard title="实时读数" description="每设备每指标最新值（60 秒自动刷新）">
        <Empty description="加载中…" />
      </SectionCard>
    )
  }
  if (query.isError || items.length === 0) {
    return (
      <SectionCard title="实时读数" description="每设备每指标最新值（60 秒自动刷新）">
        <EmptyGuide
          compact
          icon={<Activity size={28} />}
          title={query.isError ? '读数暂时不可用' : '暂无监控读数'}
          description={
            query.isError
              ? '读取失败，请稍后重试或联系管理员'
              : '监控数据来源=锅炉群人工抄表消息（采集未配置或尚未收到抄表时无读数）'
          }
        />
      </SectionCard>
    )
  }

  return (
    <SectionCard
      title="实时读数"
      description={`共 ${byEquipment.size} 台设备 ${items.length} 项指标（60 秒自动刷新）`}
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {[...byEquipment.entries()].map(([eq, metrics]) => (
          <div
            key={eq}
            style={{
              border: '1px solid rgba(148, 163, 184, 0.25)',
              borderRadius: 8,
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              {eq}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {metrics.map((m) => (
                <div key={m.metric} style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#a4a097' }}>{m.metric}</div>
                  <div
                    style={{
                      fontSize: 20,
                      fontWeight: 700,
                      lineHeight: 1.3,
                      color: STATUS_COLOR[m.status] ?? STATUS_COLOR.normal,
                    }}
                  >
                    {m.value}
                    <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 3 }}>
                      {m.unit ?? ''}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: '#a4a097' }}>
                    {fmtTime(m.recorded_at)} · {PARSE_LABEL[m.parse_method] ?? m.parse_method}
                    {m.status !== 'normal' ? ' · 越界' : ''}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

function TrendCard({ latestItems }: { latestItems: TelemetryLatestItem[] }) {
  const equipments = useMemo(
    () => [...new Set(latestItems.map((i) => i.equipment_no))],
    [latestItems],
  )
  const [equipmentNo, setEquipmentNo] = useState<string | undefined>(equipments[0])
  const effectiveEq = equipmentNo && equipments.includes(equipmentNo) ? equipmentNo : equipments[0]
  const metrics = useMemo(
    () => latestItems.filter((i) => i.equipment_no === effectiveEq).map((i) => i.metric),
    [latestItems, effectiveEq],
  )
  const [metric, setMetric] = useState<string | undefined>(undefined)
  const effectiveMetric = metric && metrics.includes(metric) ? metric : metrics[0]
  const [interval, setInterval] = useState<'hour' | 'day'>('hour')

  const query = useQuery({
    queryKey: ['telemetry-history', effectiveEq, effectiveMetric, interval],
    queryFn: () =>
      fetchTelemetryHistory({
        equipment_no: effectiveEq,
        metric: effectiveMetric,
        interval,
      }),
    enabled: Boolean(effectiveEq && effectiveMetric),
  })

  const points = query.data?.points ?? []

  return (
    <SectionCard title="趋势" description="按小时/按日桶聚合（桶内均值）">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          size="small"
          style={{ minWidth: 140 }}
          placeholder="设备"
          value={effectiveEq}
          onChange={setEquipmentNo}
          options={equipments.map((e) => ({ value: e, label: e }))}
          disabled={equipments.length === 0}
        />
        <Select
          size="small"
          style={{ minWidth: 120 }}
          placeholder="指标"
          value={effectiveMetric}
          onChange={setMetric}
          options={metrics.map((m) => ({ value: m, label: m }))}
          disabled={metrics.length === 0}
        />
        <Radio.Group
          size="small"
          value={interval}
          onChange={(e) => setInterval(e.target.value)}
          options={[
            { value: 'hour', label: '按小时' },
            { value: 'day', label: '按日' },
          ]}
        />
        {effectiveMetric ? (
          <StatusTag label={`${effectiveEq} · ${effectiveMetric}`} tone="primary" />
        ) : undefined}
      </div>
      <SingleTrendChart
        dates={points.map((p) => p.ts.slice(0, interval === 'hour' ? 13 : 10).replace('T', ' '))}
        values={points.map((p) => p.value)}
        label={`${effectiveMetric ?? ''}趋势`}
        tone="primary"
        height={280}
        emptyText={effectiveMetric ? '该指标暂无历史读数' : '先选择设备与指标'}
      />
    </SectionCard>
  )
}

const ALARM_STATUS_META: Record<string, { label: string; tone: 'danger' | 'warn' | 'ok' }> = {
  firing: { label: '待确认', tone: 'danger' },
  acked: { label: '已确认', tone: 'warn' },
  resolved: { label: '已闭环', tone: 'ok' },
}

function AlarmListCard() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [resolving, setResolving] = useState<TelemetryAlarm | null>(null)
  const [note, setNote] = useState('')

  const query = useQuery({
    queryKey: ['telemetry-alarms', statusFilter],
    queryFn: () => fetchTelemetryAlarms({ status: statusFilter as TelemetryAlarm['status'] }),
    refetchInterval: 60_000,
  })
  const items = query.data?.items ?? []

  const ackMut = useMutation({
    mutationFn: (id: string) => ackTelemetryAlarm(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['telemetry-alarms'] }),
  })
  const resolveMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => resolveTelemetryAlarm(id, note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['telemetry-alarms'] })
      setResolving(null)
      setNote('')
    },
  })

  const columns: ColumnsType<TelemetryAlarm> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const meta = ALARM_STATUS_META[v]
        return meta ? <StatusTag label={meta.label} tone={meta.tone} /> : v
      },
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 80,
      render: (v: string) => (v === 'alarm' ? <Tag color="red">报警</Tag> : <Tag color="orange">预警</Tag>),
    },
    { title: '设备', dataIndex: 'equipment_no', width: 100 },
    {
      title: '命中规则',
      dataIndex: 'rule_desc',
      render: (v: string, row) => (
        <span>
          {v}
          {row.resolution_note ? (
            <div style={{ fontSize: 12, color: '#a4a097' }}>处置：{row.resolution_note}</div>
          ) : null}
          {row.acked_by ? (
            <div style={{ fontSize: 12, color: '#a4a097' }}>
              确认：{row.acked_by}{row.acked_at ? ` · ${fmtTime(row.acked_at)}` : ''}
            </div>
          ) : null}
        </span>
      ),
    },
    { title: '读数时间', dataIndex: 'recorded_at', width: 120, render: fmtTime },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: unknown, row: TelemetryAlarm) =>
        row.status === 'firing' ? (
          <Popconfirm title="确认已接手处理该报警？" onConfirm={() => ackMut.mutate(row.id)}>
            <Button size="small" type="primary" ghost loading={ackMut.isPending && ackMut.variables === row.id}>
              值班确认
            </Button>
          </Popconfirm>
        ) : row.status === 'acked' ? (
          <Button
            size="small"
            onClick={() => {
              setResolving(row)
              setNote('')
            }}
          >
            处置闭环
          </Button>
        ) : (
          <span style={{ fontSize: 12, color: '#a4a097' }}>
            {row.resolved_at ? fmtTime(row.resolved_at) : ''} 闭环
          </span>
        ),
    },
  ]

  return (
    <SectionCard
      title="报警列表"
      description="firing → 值班确认 → 处置闭环（说明必填）；卡片按钮与 Web 同口径"
    >
      <div className="mb-3 flex items-center gap-2">
        <Radio.Group
          size="small"
          value={statusFilter ?? 'all'}
          onChange={(e) => {
            const v = e.target.value as string
            setStatusFilter(v === 'all' ? undefined : v)
          }}
          options={[
            { value: 'all', label: '全部' },
            { value: 'firing', label: '待确认' },
            { value: 'acked', label: '已确认' },
            { value: 'resolved', label: '已闭环' },
          ]}
        />
        {query.data ? <span style={{ fontSize: 12, color: '#a4a097' }}>共 {query.data.total} 条</span> : undefined}
      </div>
      <Table
        columns={columns}
        dataSource={items}
        rowKey="id"
        size="small"
        loading={query.isLoading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        locale={{
          emptyText: (
            <EmptyGuide
              compact
              icon={<Activity size={28} />}
              title="暂无报警"
              description="读数在阈值规则内，或采集尚未产生数据"
            />
          ),
        }}
      />
      <Modal
        title={`处置闭环：${resolving?.equipment_no ?? ''} ${resolving?.metric ?? ''}`}
        open={resolving !== null}
        onOk={() => resolving && resolveMut.mutate({ id: resolving.id, note })}
        confirmLoading={resolveMut.isPending}
        onCancel={() => setResolving(null)}
        okButtonProps={{ disabled: !note.trim() }}
      >
        <div style={{ marginBottom: 8, fontSize: 12, color: '#a4a097' }}>
          {resolving?.rule_desc}
        </div>
        <Input.TextArea
          rows={3}
          placeholder="处置说明（必填，将留痕）"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Modal>
    </SectionCard>
  )
}

function PendingReviewCard() {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState<TelemetryPendingReview | null>(null)
  const [equipmentNo, setEquipmentNo] = useState('')
  const [metric, setMetric] = useState('')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')

  const query = useQuery({
    queryKey: ['telemetry-pending-reviews'],
    queryFn: () => fetchTelemetryPendingReviews(),
    refetchInterval: 120_000,
  })
  const items = query.data?.items ?? []

  const confirmMut = useMutation({
    mutationFn: (id: string) =>
      confirmTelemetryPendingReview(id, {
        equipment_no: equipmentNo,
        readings: [{ metric: metric.trim(), value: Number(value), unit: unit.trim() || undefined }],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['telemetry-pending-reviews'] })
      qc.invalidateQueries({ queryKey: ['telemetry-latest'] })
      setConfirming(null)
    },
  })

  const columns: ColumnsType<TelemetryPendingReview> = [
    { title: '消息时间', dataIndex: 'recorded_at', width: 120, render: fmtTime },
    {
      title: '原消息摘录',
      dataIndex: 'raw_excerpt',
      render: (v: string | null, row) => (
        <span>
          {v || '（无文本，可能是图片消息）'}
          {row.metric ? (
            <div style={{ fontSize: 12, color: '#a4a097' }}>
              已抽出：{row.metric} = {row.value} {row.unit ?? ''}
            </div>
          ) : null}
        </span>
      ),
    },
    { title: '解析方式', dataIndex: 'parse_method', width: 90, render: (v) => PARSE_LABEL[v] ?? v },
    {
      title: '操作',
      key: 'actions',
      width: 110,
      render: (_: unknown, row: TelemetryPendingReview) => (
        <Button
          size="small"
          onClick={() => {
            setConfirming(row)
            setEquipmentNo(row.equipment_no ?? '')
            setMetric(row.metric ?? '')
            setValue(row.value !== null ? String(row.value) : '')
            setUnit(row.unit ?? '')
          }}
        >
          补录确认
        </Button>
      ),
    },
  ]

  return (
    <SectionCard
      title="解析失败待补录"
      description="模板与 AI 都未能可靠解析的消息（不丢弃）；人工确认数值后转正入快照"
    >
      <Table
        columns={columns}
        dataSource={items}
        rowKey="id"
        size="small"
        loading={query.isLoading}
        pagination={{ pageSize: 10 }}
        locale={{
          emptyText: (
            <EmptyGuide
              compact
              title="无待补录消息"
              description="解析链健康：模板或 AI 已处理全部新消息"
            />
          ),
        }}
      />
      <Modal
        title="人工补录确认"
        open={confirming !== null}
        onOk={() => confirming && confirmMut.mutate(confirming.id)}
        confirmLoading={confirmMut.isPending}
        onCancel={() => setConfirming(null)}
        okButtonProps={{ disabled: !equipmentNo.trim() || !metric.trim() || value === '' }}
      >
        <div style={{ marginBottom: 8, fontSize: 12, color: '#a4a097' }}>
          原消息：{confirming?.raw_excerpt || '（图片消息）'}
        </div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Input
            size="small"
            style={{ width: 140 }}
            placeholder="设备编号（必填）"
            value={equipmentNo}
            onChange={(e) => setEquipmentNo(e.target.value)}
          />
          <Input
            size="small"
            style={{ width: 120 }}
            placeholder="指标（必填）"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
          />
          <Input
            size="small"
            style={{ width: 110 }}
            placeholder="数值（必填）"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <Input
            size="small"
            style={{ width: 90 }}
            placeholder="单位"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
        </div>
      </Modal>
    </SectionCard>
  )
}

export default function TelemetryMonitorPanel() {
  // 读数卡与趋势选择器共用一次 latest 请求（设备/指标清单两处消费）
  const latest = useQuery({
    queryKey: ['telemetry-latest'],
    queryFn: () => fetchTelemetryLatest(),
    refetchInterval: 60_000,
  })
  const latestItems = latest.data?.items ?? []

  return (
    <div className="flex flex-col gap-4">
      <ReadingsCard query={latest} />
      <TrendCard latestItems={latestItems} />
      <AlarmListCard />
      <PendingReviewCard />
    </div>
  )
}
