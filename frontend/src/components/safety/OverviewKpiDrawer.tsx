'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Button, Drawer, Spin, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import { ArrowRight } from 'lucide-react'
import dayjs from 'dayjs'
import {
  EmptyGuide,
  RankBarChart,
  StatusTag,
  TONE_HEX,
  TrendAreaChart,
  type Tone,
} from '@/components/ui-kit'
import { MarkdownView } from '@/components/toolbox/MarkdownView'
import { normalizeHazardLevel, RECTIFICATION_STATUS_OPTIONS } from '@/types/safety'
import { OP_TYPE_CONFIG } from '@/components/safety/specialOpsConstants'
import { fetchHazards } from '@/lib/api/safety/hazard'
import { fetchSpecialOperationLedger } from '@/lib/api/safety/special-ops'
import { fetchFireAlarmRecords } from '@/lib/api/safety/fire-alarm'
import { fetchCentralAlarmRecords } from '@/lib/api/safety/central-alarm'
import { fetchCertWarnings } from '@/lib/api/safety/cert-warning'
import type { SafetyOverview } from '@/lib/api/safety/overview'

/**
 * 总览驾驶舱 KPI 抽屉——六格统一「点击开抽屉看明细」（只读态势不下沉页面）。
 *
 * 数据口径：
 * - 隐患/速递/报警分析/超储：总览聚合载荷（一次拉取的同一份数据）
 * - 隐患清单走 GET /hazards?rectification_status=unclosed（≠closed，与 KPI 口径互补）
 * - 特作清单走 /special-operation-ledger 当日（台账口径：审批中+已通过）
 * - 报警明细走 fire/central records 当日两源分列；证书走 /cert-warnings 30 天全量
 *
 * active 透传到 useQuery.enabled：关闭动画期间不触发新请求，卸载即销毁缓存。
 */

export type OverviewKpiKey =
  | 'hazards'
  | 'special_ops'
  | 'alarms'
  | 'certs'
  | 'chemicals'
  | 'digest'

const KPI_TITLE: Record<OverviewKpiKey, string> = {
  hazards: '未闭环隐患',
  special_ops: '今日特殊作业',
  alarms: '今日报警',
  certs: '30 天内到期证书',
  chemicals: '危化品超储',
  digest: '今日安全速递',
}

/** 抽屉「前往模块页」导航（速递只存在于飞书推送，无落地页） */
const KPI_NAV: Partial<Record<OverviewKpiKey, { path: string; label: string }>> = {
  hazards: { path: '/safety/hazard-ledger', label: '隐患排查与治理' },
  special_ops: { path: '/safety/special-ops', label: '特殊作业管理' },
  alarms: { path: '/safety/alarms', label: '监测报警与预警' },
  certs: { path: '/safety/cert-warnings', label: '人员准入与资质' },
  chemicals: { path: '/safety/chemicals', label: '危化品与 MSDS 管理' },
}

function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = dayjs(value)
  return d.isValid() ? d.format('MM-DD HH:mm') : '—'
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD') : '—'
}

/** 只读短列表注入稳定行键（明细无唯一 id 字段；antd rowKey 的 index 参数已废弃） */
function withRowKeys<T extends object>(items: T[]): (T & { _key: number })[] {
  return items.map((it, idx) => ({ ...it, _key: idx }))
}

/** 采集失败区块的统一空态（域置 None 时） */
function DegradedSection({ domain }: { domain: string }) {
  return (
    <EmptyGuide
      compact
      title={`${domain}数据暂时不可用`}
      description="该域采集失败（如多维表格抖动），稍后自动恢复"
    />
  )
}

/** 抽屉顶部小结条：KPI 口径数字 + 说明 */
function SummaryStrip({ items }: { items: { label: string; value: React.ReactNode }[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-x-6 gap-y-2 rounded-lg bg-[var(--color-surface)] px-4 py-2.5">
      {items.map(it => (
        <div key={it.label} className="flex items-baseline gap-1.5">
          <span className="text-[12px] text-[var(--color-steel)]">{it.label}</span>
          <span className="text-[16px] font-semibold tabular-nums text-[var(--color-charcoal)]">
            {it.value}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── 1. 未闭环隐患 ──

const HAZARD_LEVEL_TONE: Record<string, Tone> = {
  major: 'danger',
  serious: 'warn',
  general: 'info',
}
const HAZARD_LEVEL_LABEL: Record<string, string> = {
  general: '一般隐患',
  serious: '较大隐患',
  major: '重大隐患',
}

function rectificationStatusLabel(value: string | null): string {
  if (!value) return '—'
  return RECTIFICATION_STATUS_OPTIONS.find(o => o.value === value)?.label ?? value
}

function HazardsDrawerContent({
  overview,
  active,
}: {
  overview: SafetyOverview | null
  active: boolean
}) {
  const hazards = overview?.hazards
  const { data, isLoading } = useQuery({
    queryKey: ['safety', 'overview-drawer', 'hazards-unclosed'],
    queryFn: () =>
      fetchHazards({ rectification_status: 'unclosed', page: 1, page_size: 200 }),
    enabled: active,
  })

  const columns: TableColumnsType<
    Awaited<ReturnType<typeof fetchHazards>>['items'][number] & { _key: number }
  > = [
    { title: '隐患描述', dataIndex: 'description', ellipsis: true },
    {
      title: '等级',
      dataIndex: 'hazard_level',
      width: 96,
      render: (v: string | null, record) => {
        const raw = record.hazard_level_manual || v
        const key = normalizeHazardLevel(raw)
        return (
          <StatusTag
            tone={HAZARD_LEVEL_TONE[key] ?? 'default'}
            label={HAZARD_LEVEL_LABEL[key] ?? raw ?? '—'}
          />
        )
      },
    },
    {
      title: '责任部门',
      dataIndex: 'department',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: '发现时间',
      dataIndex: 'discovered_at',
      width: 104,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: '整改期限',
      dataIndex: 'deadline',
      width: 128,
      render: (v: string | null) => {
        if (!v) return '—'
        const overdue = dayjs(v).isBefore(dayjs(), 'day')
        return (
          <StatusTag tone={overdue ? 'expired' : 'default'} label={fmtDate(v)} />
        )
      },
    },
    {
      title: '整改状态',
      dataIndex: 'rectification_status',
      width: 92,
      render: (v: string | null) => rectificationStatusLabel(v),
    },
  ]

  if (!overview) return <Spin className="block w-full text-center" />
  if (!hazards) return <DegradedSection domain="隐患" />

  return (
    <div className="flex flex-col gap-3">
      <SummaryStrip
        items={[
          { label: '未闭环', value: hazards.unclosed },
          {
            label: '较昨日',
            value: (
              <StatusTag
                tone={hazards.delta > 0 ? 'danger' : hazards.delta < 0 ? 'ok' : 'default'}
                label={hazards.delta > 0 ? `+${hazards.delta}` : hazards.delta < 0 ? `${hazards.delta}` : '持平'}
              />
            ),
          },
          { label: '逾期', value: hazards.overdue },
          { label: '清单条数', value: data?.total ?? '…' },
        ]}
      />
      <div className="h-[150px]">
        <TrendAreaChart
          dates={hazards.trend.dates.map(d => d.slice(5))}
          seriesA={hazards.trend.created}
          seriesB={hazards.trend.closed}
          labelA="新增"
          labelB="闭环"
          toneA="danger"
          toneB="ok"
          height={150}
          emptyText="近 30 天暂无隐患动态"
        />
      </div>
      <Table
        rowKey={r => r._key}
        size="small"
        loading={isLoading}
        columns={columns}
        dataSource={withRowKeys(data?.items ?? [])}
        pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: '暂无未闭环隐患' }}
      />
    </div>
  )
}

// ── 2. 今日特殊作业 ──

function specialOpsStatusLabel(v: string | null): { label: string; tone: Tone } {
  if (v === 'approved') return { label: '已通过', tone: 'ok' }
  if (v === 'submitted') return { label: '审批中', tone: 'warn' }
  return { label: v ?? '—', tone: 'default' }
}

function SpecialOpsDrawerContent({
  overview,
  active,
}: {
  overview: SafetyOverview | null
  active: boolean
}) {
  const today = dayjs().format('YYYY-MM-DD')
  const specialOps = overview?.special_ops
  const { data, isLoading } = useQuery({
    queryKey: ['safety', 'overview-drawer', 'special-ops-today'],
    queryFn: () =>
      fetchSpecialOperationLedger({ date_from: today, date_to: today, page_size: 200 }),
    enabled: active,
  })

  const columns: TableColumnsType<
    Awaited<ReturnType<typeof fetchSpecialOperationLedger>>['items'][number] & { _key: number }
  > = [
    {
      title: '作业类型',
      dataIndex: 'operation_type',
      width: 96,
      render: (v: string | null) => OP_TYPE_CONFIG[v ?? '']?.label ?? v ?? '—',
    },
    {
      title: '作业内容',
      dataIndex: 'work_description',
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: '部门',
      dataIndex: 'department',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: '计划开始',
      dataIndex: 'planned_start_time',
      width: 104,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: '风险',
      dataIndex: 'is_critical',
      width: 76,
      render: (v: boolean) =>
        v ? <StatusTag tone="danger" label="高风险" /> : <StatusTag tone="ok" label="常规" />,
    },
    {
      title: '审批状态',
      dataIndex: 'status',
      width: 88,
      render: (v: string | null) => {
        const s = specialOpsStatusLabel(v)
        return <StatusTag tone={s.tone} label={s.label} />
      },
    },
  ]

  if (!overview) return <Spin className="block w-full text-center" />
  if (!specialOps) return <DegradedSection domain="特殊作业" />

  return (
    <div className="flex flex-col gap-3">
      <SummaryStrip
        items={[
          { label: '今日作业（日报口径）', value: specialOps.today_total },
          { label: '高风险', value: specialOps.high },
          { label: '台账当日清单', value: data?.total ?? '…' },
        ]}
      />
      <Table
        rowKey={r => r._key}
        size="small"
        loading={isLoading}
        columns={columns}
        dataSource={withRowKeys(data?.items ?? [])}
        pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: '今日暂无特殊作业报备' }}
      />
    </div>
  )
}

// ── 3. 今日报警 ──

function AlarmsDrawerContent({
  overview,
  active,
}: {
  overview: SafetyOverview | null
  active: boolean
}) {
  const today = dayjs().format('YYYY-MM-DD')
  const alarms = overview?.alarms
  const analysis = alarms?.analysis
  const fireQuery = useQuery({
    queryKey: ['safety', 'overview-drawer', 'fire-alarms-today'],
    queryFn: () => fetchFireAlarmRecords({ date_from: today, date_to: today, page_size: 100 }),
    enabled: active,
  })
  const centralQuery = useQuery({
    queryKey: ['safety', 'overview-drawer', 'central-alarms-today'],
    queryFn: () =>
      fetchCentralAlarmRecords({ date_from: today, date_to: today, page_size: 100 }),
    enabled: active,
  })

  const fireColumns: TableColumnsType<
    Awaited<ReturnType<typeof fetchFireAlarmRecords>>['items'][number] & { _key: number }
  > = [
    {
      title: '时间',
      dataIndex: 'alarm_time',
      width: 84,
      render: (v: string | null) => (v ? dayjs(v).format('HH:mm') : '—'),
    },
    {
      title: '报警类型',
      dataIndex: 'alarm_type',
      width: 120,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: '部位/建筑',
      dataIndex: 'location',
      ellipsis: true,
      render: (v: string | null, record) => [record.building, v].filter(Boolean).join(' · ') || '—',
    },
    {
      title: '性质',
      dataIndex: 'alarm_nature',
      width: 96,
      render: (v: string | null) =>
        v ? (
          <StatusTag tone={v.includes('真实') ? 'danger' : 'default'} label={v} />
        ) : (
          '—'
        ),
    },
  ]

  const centralColumns: TableColumnsType<
    Awaited<ReturnType<typeof fetchCentralAlarmRecords>>['items'][number] & { _key: number }
  > = [
    {
      title: '时间',
      dataIndex: 'alarm_date',
      width: 84,
      render: (v: string | null) => (v ? dayjs(v).format('HH:mm') : '—'),
    },
    {
      title: '车间/产线',
      dataIndex: 'workshop',
      ellipsis: true,
      render: (v: string | null, record) =>
        [v, record.line].filter(Boolean).join(' · ') || '—',
    },
    {
      title: '岗位',
      dataIndex: 'post',
      width: 100,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: '报警情况',
      dataIndex: 'alarm_description',
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
  ]

  if (!overview) return <Spin className="block w-full text-center" />
  if (!alarms || !analysis) return <DegradedSection domain="报警" />

  return (
    <div className="flex flex-col gap-4">
      <SummaryStrip
        items={[
          { label: '今日合计', value: alarms.today_total },
          { label: '消防', value: alarms.fire_today },
          { label: '中控', value: alarms.central_today },
          { label: '真报（消防口径）', value: alarms.fire_real_today },
        ]}
      />
      <div className="h-[150px]">
        <TrendAreaChart
          dates={analysis.dates.map(d => d.slice(5))}
          seriesA={analysis.fire_daily}
          seriesB={analysis.central_daily}
          labelA="消防"
          labelB="中控"
          toneA="danger"
          toneB="info"
          height={150}
          emptyText="近 7 日暂无报警"
        />
      </div>
      {analysis.top_fire_types.length > 0 && (
        <div className="h-[110px]">
          <div className="mb-1 text-[12px] text-[var(--color-stone)]">
            Top 报警类型（近 7 日 · 消防口径）
          </div>
          <RankBarChart
            names={analysis.top_fire_types.map(t => t.name)}
            values={analysis.top_fire_types.map(t => t.count)}
            height={80}
            color={TONE_HEX.danger}
            emptyText=""
          />
        </div>
      )}
      <div>
        <div className="mb-1 text-[13px] font-medium text-[var(--color-charcoal)]">
          消防报警（今日 {fireQuery.data?.total ?? alarms.fire_today}）
        </div>
        <Table
          rowKey={r => r._key}
          size="small"
          loading={fireQuery.isLoading}
          columns={fireColumns}
          dataSource={withRowKeys(fireQuery.data?.items ?? [])}
          pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
          locale={{ emptyText: '今日暂无消防报警' }}
        />
      </div>
      <div>
        <div className="mb-1 text-[13px] font-medium text-[var(--color-charcoal)]">
          中控报警（今日 {centralQuery.data?.total ?? alarms.central_today}）
        </div>
        <Table
          rowKey={r => r._key}
          size="small"
          loading={centralQuery.isLoading}
          columns={centralColumns}
          dataSource={withRowKeys(centralQuery.data?.items ?? [])}
          pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
          locale={{ emptyText: '今日暂无中控报警' }}
        />
      </div>
    </div>
  )
}

// ── 4. 30 天内到期证书 ──

function certCategoryLabel(category: string): string {
  const map: Record<string, string> = {
    special_op: '特种作业证',
    guardian_a: '监护人证（化学）',
    guardian_b: '监护人证（电气）',
  }
  return map[category] ?? category
}

function remainingDaysTone(days: number | null): Tone {
  if (days === null) return 'default'
  if (days < 0) return 'expired'
  if (days <= 7) return 'danger'
  if (days <= 30) return 'warn'
  return 'ok'
}

function CertsDrawerContent({
  overview,
  active,
}: {
  overview: SafetyOverview | null
  active: boolean
}) {
  const certs = overview?.certs
  const { data, isLoading } = useQuery({
    queryKey: ['safety', 'overview-drawer', 'certs-30d'],
    queryFn: () => fetchCertWarnings({ days_within: 30, page: 1, page_size: 200 }),
    enabled: active,
  })

  const columns: TableColumnsType<
    Awaited<ReturnType<typeof fetchCertWarnings>>['items'][number] & { _key: number }
  > = [
    { title: '姓名', dataIndex: 'person_name', width: 90 },
    {
      title: '部门',
      dataIndex: 'department',
      width: 130,
      render: (v: string | null) => v || '—',
    },
    {
      title: '证书',
      dataIndex: 'cert_category',
      width: 140,
      render: (v: string) => certCategoryLabel(v),
    },
    {
      title: '到期日',
      dataIndex: 'deadline',
      width: 110,
      render: (v: string | null) => fmtDate(v),
    },
    {
      title: '剩余天数',
      dataIndex: 'remaining_days',
      width: 96,
      render: (v: number | null) =>
        v === null ? '—' : <StatusTag tone={remainingDaysTone(v)} label={`${v} 天`} />,
    },
  ]

  if (!overview) return <Spin className="block w-full text-center" />
  if (!certs) return <DegradedSection domain="到期证书" />

  return (
    <div className="flex flex-col gap-3">
      <SummaryStrip
        items={[
          { label: '30 天内到期', value: certs.within_30d },
          { label: '8 天内/已逾期', value: certs.urgent_or_overdue },
        ]}
      />
      <Table
        rowKey={r => r._key}
        size="small"
        loading={isLoading}
        columns={columns}
        dataSource={withRowKeys(data?.items ?? [])}
        pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: '30 天内无到期证书' }}
      />
    </div>
  )
}

// ── 5. 危化品超储 ──

function ChemicalsDrawerContent({ overview }: { overview: SafetyOverview | null }) {
  const chemicals = overview?.chemicals

  const columns: TableColumnsType<
    NonNullable<SafetyOverview['chemicals']>['materials'][number] & { _key: number }
  > = [
    { title: '品名', dataIndex: 'material_name', ellipsis: true },
    {
      title: '部门',
      dataIndex: 'department',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: '存放位置',
      dataIndex: 'storage_location',
      width: 110,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: '存量/上限',
      dataIndex: 'total_quantity_t',
      width: 120,
      render: (v: number, record) =>
        `${v}${record.unit ?? ''} / ${record.max_limit}${record.unit ?? ''}`,
    },
    {
      title: '超储幅度',
      dataIndex: 'max_limit',
      width: 130,
      render: (v: number, record) => {
        const over = record.total_quantity_t - v
        const ratio = v > 0 ? (over / v) * 100 : 0
        return (
          <StatusTag
            tone={ratio >= 50 ? 'danger' : 'warn'}
            label={`+${over.toFixed(1)}${record.unit ?? ''}（${ratio.toFixed(0)}%）`}
          />
        )
      },
    },
  ]

  if (!overview) return <Spin className="block w-full text-center" />
  if (!chemicals) return <DegradedSection domain="危化品" />

  return (
    <div className="flex flex-col gap-3">
      <SummaryStrip
        items={[
          { label: '超储物料', value: chemicals.over_limit },
          { label: '判定口径', value: <span className="text-[13px]">存量 &gt; 上限</span> },
        ]}
      />
      <Table
        rowKey={r => r._key}
        size="small"
        columns={columns}
        dataSource={withRowKeys(chemicals.materials)}
        pagination={false}
        locale={{ emptyText: '无超储物料' }}
      />
    </div>
  )
}

// ── 6. 今日安全速递 ──

function DigestDrawerContent({ overview }: { overview: SafetyOverview | null }) {
  const digest = overview?.digest
  if (!overview) return <Spin className="block w-full text-center" />
  if (!digest) return <DegradedSection domain="速递" />
  if (digest.cells.length === 0) {
    return (
      <EmptyGuide
        compact
        title="今日速递尚未推送"
        description="各日报在预定时点由机器人自动推送后在此回放"
      />
    )
  }
  return (
    <div className="flex flex-col gap-5">
      {digest.cells.map(cell => (
        <div key={cell.key} className="rounded-lg border border-[var(--color-hairline)] p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Tag color="blue">{cell.tag_text}</Tag>
              <span className="text-[14px] font-medium text-[var(--color-charcoal)]">
                {cell.title}
              </span>
            </div>
            <span className="text-[12px] text-[var(--color-steel)]">
              {cell.sent_at ? dayjs(cell.sent_at).format('HH:mm') : '—'} 推送
            </span>
          </div>
          <MarkdownView
            text={[cell.stats, cell.zone, '---', cell.detail].filter(Boolean).join('\n\n')}
          />
        </div>
      ))}
    </div>
  )
}

// ── 外壳 ──

export function OverviewKpiDrawer({
  kpi,
  active,
  overview,
  onClose,
}: {
  /** 当前打开的 KPI；null=关闭（关闭动画期间仍渲染上次内容） */
  kpi: OverviewKpiKey | null
  active: boolean
  overview: SafetyOverview | null
  onClose: () => void
}) {
  const router = useRouter()
  const nav = kpi ? KPI_NAV[kpi] : undefined
  return (
    <Drawer
      open={active}
      onClose={onClose}
      size={kpi === 'digest' ? 640 : 960}
      title={
        kpi ? (
          <span>
            {KPI_TITLE[kpi]}
            {overview?.date && (
              <span className="ml-2 text-[13px] font-normal text-[var(--color-steel)]">
                {overview.date}
              </span>
            )}
          </span>
        ) : null
      }
      extra={
        nav ? (
          <Button
            type="link"
            size="small"
            icon={<ArrowRight size={13} />}
            iconPosition="end"
            onClick={() => {
              onClose()
              router.push(nav.path)
            }}
          >
            前往{nav.label}
          </Button>
        ) : null
      }
    >
      {kpi === 'hazards' && <HazardsDrawerContent overview={overview} active={active} />}
      {kpi === 'special_ops' && (
        <SpecialOpsDrawerContent overview={overview} active={active} />
      )}
      {kpi === 'alarms' && <AlarmsDrawerContent overview={overview} active={active} />}
      {kpi === 'certs' && <CertsDrawerContent overview={overview} active={active} />}
      {kpi === 'chemicals' && <ChemicalsDrawerContent overview={overview} />}
      {kpi === 'digest' && <DigestDrawerContent overview={overview} />}
    </Drawer>
  )
}
