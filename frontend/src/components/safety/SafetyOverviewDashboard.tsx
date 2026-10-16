'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { Button, Col, Modal, Row, Spin, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  FileText,
  RefreshCw,
  Siren,
  TriangleAlert,
} from 'lucide-react'
import dayjs from 'dayjs'
import {
  EmptyGuide,
  FeedRow,
  PageHeader,
  RankBarChart,
  SectionCard,
  StatCard,
  StatDelta,
  StatusTag,
  TONE_HEX,
  TrendAreaChart,
  type Tone,
} from '@/components/ui-kit'
import { MarkdownView } from '@/components/toolbox/MarkdownView'
import { moduleMenus } from '@/lib/menu-config'
import {
  fetchSafetyOverview,
  type OverviewDigestCell,
  type OverviewKeyRiskOps,
  type OverviewCerts,
  type OverviewChemicals,
  type OverviewModuleHealth,
} from '@/lib/api/safety/overview'

/** 飞书 text_tag 颜色 → 语义 Tone（速递流标签用） */
const FEISHU_TAG_TONE: Record<string, Tone> = {
  red: 'danger',
  blue: 'info',
  orange: 'warn',
  indigo: 'primary',
  yellow: 'warn',
  green: 'ok',
}

const HEALTH_STATUS_LABEL: Record<string, string> = {
  ok: '正常',
  warn: '预警',
  inactive: '未接入', // 四期起四新域为真实页面，「未接入」=建表接入前常态
  upcoming: '未上线',
}

const HEALTH_STATUS_TONE: Record<string, Tone> = {
  ok: 'ok',
  warn: 'warn',
  inactive: 'default',
  upcoming: 'default',
}

/** 健康度墙模块清单：从一期菜单推导（工作台/系统组除外），保证与菜单结构性对齐 */
const HEALTH_WALL = (() => {
  const safety = moduleMenus.find(m => m.key === 'safety')
  return (safety?.children ?? []).filter(
    item => item.group && item.group !== '工作台' && item.group !== '系统',
  )
})()

function sentAtText(sentAt: string | null): string {
  if (!sentAt) return '—'
  const d = dayjs(sentAt)
  return d.isValid() ? d.format('HH:mm') : '—'
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const d = dayjs(value)
  return d.isValid() ? d.format('MM-DD HH:mm') : '—'
}

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

/** 采集失败区块的统一空态 */
function DegradedSection({ domain }: { domain: string }) {
  return (
    <EmptyGuide
      compact
      icon={<TriangleAlert size={18} />}
      title={`${domain}数据暂时不可用`}
      description="该域采集失败（如多维表格抖动），稍后自动恢复；详情见页面底部错误标注"
    />
  )
}

/** 只读短列表注入稳定行键（明细无唯一 id 字段；antd rowKey 的 index 参数已废弃） */
function withRowKeys<T extends object>(items: T[]): (T & { _key: number })[] {
  return items.map((it, idx) => ({ ...it, _key: idx }))
}

function KpiSection({
  data,
  loading,
}: {
  data: ReturnType<typeof useOverviewData>['data']
  loading: boolean
}) {
  const router = useRouter()
  const hazards = data?.hazards
  const specialOps = data?.special_ops
  const alarms = data?.alarms
  const certs = data?.certs
  const chemicals = data?.chemicals
  const digest = data?.digest

  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} sm={12} xl={4}>
        <StatCard
          emphasized
          label="未闭环隐患"
          tone={hazards && hazards.overdue > 0 ? 'warn' : 'primary'}
          icon={<AlertTriangle size={16} />}
          loading={loading}
          value={hazards?.unclosed ?? 0}
          sub={
            hazards ? (
              <span>
                较昨日 <StatDelta value={hazards.delta} invert />
                {hazards.overdue > 0 && ` · 逾期 ${hazards.overdue}`}
              </span>
            ) : undefined
          }
          onClick={() => router.push('/safety/hazard-ledger')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="今日特殊作业"
          tone={specialOps && specialOps.high > 0 ? 'danger' : 'ok'}
          icon={<ClipboardList size={16} />}
          loading={loading}
          value={specialOps?.today_total ?? 0}
          sub={`高风险 ${specialOps?.high ?? 0} 项`}
          onClick={() => router.push('/safety/special-ops')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="今日报警"
          tone={alarms && alarms.fire_real_today > 0 ? 'danger' : 'info'}
          icon={<Siren size={16} />}
          loading={loading}
          value={alarms?.today_total ?? 0}
          sub={`真报 ${alarms?.fire_real_today ?? 0} 起（消防口径）`}
          onClick={() => router.push('/safety/alarms')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="30 天内到期证书"
          tone={certs && certs.urgent_or_overdue > 0 ? 'warn' : 'default'}
          icon={<FileText size={16} />}
          loading={loading}
          value={certs?.within_30d ?? 0}
          sub={certs ? `8 天内/已逾期 ${certs.urgent_or_overdue} 人` : undefined}
          onClick={() => router.push('/safety/cert-warnings')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="危化品超储"
          tone={chemicals && chemicals.over_limit > 0 ? 'warn' : 'ok'}
          icon={<Boxes size={16} />}
          loading={loading}
          value={chemicals?.over_limit ?? 0}
          sub="存量超上限物料"
          onClick={() => router.push('/safety/chemicals')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="今日安全速递"
          tone="info"
          icon={<FileText size={16} />}
          loading={loading}
          value={digest?.count ?? 0}
          sub="机器人已推送日报条数"
        />
      </Col>
    </Row>
  )
}

function DigestSection({
  cells,
  degraded,
  onOpenCell,
}: {
  cells: OverviewDigestCell[] | null
  degraded: boolean
  onOpenCell: (cell: OverviewDigestCell) => void
}) {
  return (
    <SectionCard
      title="今日安全速递"
      description="机器人已推送的日报回放，点击条目看全文"
    >
      {degraded ? (
        <DegradedSection domain="速递" />
      ) : !cells || cells.length === 0 ? (
        <EmptyGuide
          compact
          icon={<FileText size={18} />}
          title="今日速递尚未推送"
          description="各日报在预定时点由机器人自动推送后在此回放"
        />
      ) : (
        <div className="flex flex-col gap-3">
          {cells.map(cell => (
            <FeedRow
              key={cell.key}
              title={cell.title}
              right={sentAtText(cell.sent_at)}
              tag={FEISHU_TAG_TONE[cell.tag_color] ?? 'info'}
              tagLabel={cell.tag_text}
              onClick={() => onOpenCell(cell)}
            />
          ))}
        </div>
      )}
    </SectionCard>
  )
}

function HealthWall({ health }: { health: OverviewModuleHealth[] | null }) {
  const router = useRouter()
  const byKey = new Map((health ?? []).map(h => [h.key, h]))

  const groups: { group: string; items: typeof HEALTH_WALL }[] = []
  for (const item of HEALTH_WALL) {
    const last = groups[groups.length - 1]
    if (last && last.group === item.group) {
      last.items.push(item)
    } else {
      groups.push({ group: item.group ?? '', items: [item] })
    }
  }

  return (
    <SectionCard
      title="体系模块健康度"
      description="按体系要素分组的 17 个模块状态，点击直达模块页"
      className="h-full"
      bodyClassName="max-h-[860px] overflow-y-auto"
    >
      <div className="flex flex-col gap-4">
        {groups.map(({ group, items }) => (
          <div key={group}>
            <div className="mb-1.5 text-[12px] font-medium uppercase tracking-wide text-[var(--color-stone)]">
              {group}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {items.map(item => {
                const state = byKey.get(item.key)
                const status = state?.status ?? 'ok'
                const clickable = !item.disabled && status !== 'upcoming'
                // S2 法规标准与规程：健康墙卡直达采集监控 Tab（菜单入口仍默认清单检索）
                const target =
                  item.key === 'knowledge-base' && item.path
                    ? `${item.path}?tab=monitor`
                    : item.path
                return (
                  <div
                    key={item.key}
                    data-testid="module-card"
                    role={clickable ? 'button' : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    onClick={
                      clickable && item.path
                        ? () => router.push(target as string)
                        : undefined
                    }
                    onKeyDown={
                      clickable
                        ? e => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              if (item.path) router.push(target as string)
                            }
                          }
                        : undefined
                    }
                    className={`rounded-lg border px-3 py-2 transition-colors ${
                      clickable
                        ? 'cursor-pointer border-[var(--color-hairline)] hover:bg-[var(--color-surface)]'
                        : 'cursor-default border-dashed border-[var(--color-hairline-soft)] opacity-80'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
                        {item.label}
                      </span>
                      <StatusTag
                        tone={HEALTH_STATUS_TONE[status]}
                        label={HEALTH_STATUS_LABEL[status] ?? status}
                      />
                    </div>
                    <div className="mt-0.5 truncate text-[12px] text-[var(--color-steel)]">
                      {state?.metric ?? '—'}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

function KeyRiskOpsTable({ data }: { data: OverviewKeyRiskOps | null }) {
  const columns: TableColumnsType<OverviewKeyRiskOps['items'][number] & { _key: number }> = [
    {
      title: '开始时间',
      dataIndex: 'start_time',
      width: 110,
      render: (v: string | null) => formatDateTime(v),
    },
    { title: '部门', dataIndex: 'department', width: 100, render: (v: string | null) => v || '—' },
    { title: '作业内容', dataIndex: 'operation_content', ellipsis: true },
    {
      title: '审批状态',
      dataIndex: 'apply_status',
      width: 90,
      render: (v: string | null) =>
        v === '已通过' ? (
          <StatusTag tone="ok" label={v} />
        ) : (
          <StatusTag tone="warn" label={v ?? '—'} />
        ),
    },
  ]
  return (
    <SectionCard
      title="今日关键风险作业"
      description={`今日已通过 ${data?.today_approved ?? 0} 项 · 审批中 ${data?.in_progress ?? 0} 项`}
    >
      {data ? (
        <Table
          rowKey={r => r._key}
          size="small"
          columns={columns}
          dataSource={withRowKeys(data.items)}
          pagination={false}
          locale={{ emptyText: '今日暂无关键风险作业报备' }}
        />
      ) : (
        <DegradedSection domain="关键风险作业" />
      )}
    </SectionCard>
  )
}

function ExpiringCertsTable({ data }: { data: OverviewCerts | null }) {
  const columns: TableColumnsType<OverviewCerts['items'][number] & { _key: number }> = [
    { title: '姓名', dataIndex: 'person_name', width: 80 },
    {
      title: '部门',
      dataIndex: 'department',
      width: 110,
      render: (v: string | null) => v || '—',
    },
    {
      title: '证书',
      dataIndex: 'cert_category',
      width: 120,
      render: (v: string) => certCategoryLabel(v),
    },
    {
      title: '到期日',
      dataIndex: 'deadline',
      width: 100,
      render: (v: string | null) => (v ? v.slice(0, 10) : '—'),
    },
    {
      title: '剩余天数',
      dataIndex: 'remaining_days',
      width: 90,
      render: (v: number | null) =>
        v === null ? '—' : <StatusTag tone={remainingDaysTone(v)} label={`${v} 天`} />,
    },
  ]
  return (
    <SectionCard
      title="30 天内到期证书"
      description={data ? `共 ${data.within_30d} 人（8 天内/已逾期 ${data.urgent_or_overdue} 人）` : undefined}
    >
      {data ? (
        <Table
          rowKey={r => r._key}
          size="small"
          columns={columns}
          dataSource={withRowKeys(data.items)}
          pagination={false}
          locale={{ emptyText: '30 天内无到期证书' }}
        />
      ) : (
        <DegradedSection domain="到期证书" />
      )}
    </SectionCard>
  )
}

function OverLimitTable({ data }: { data: OverviewChemicals | null }) {
  const columns: TableColumnsType<OverviewChemicals['materials'][number] & { _key: number }> = [
    { title: '品名', dataIndex: 'material_name', ellipsis: true },
    {
      title: '部门',
      dataIndex: 'department',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: '存量/上限',
      dataIndex: 'total_quantity_t',
      width: 110,
      render: (v: number, record) =>
        `${v}${record.unit ?? ''} / ${record.max_limit}${record.unit ?? ''}`,
    },
    {
      title: '超储幅度',
      dataIndex: 'max_limit',
      width: 90,
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
  return (
    <SectionCard
      title="超储物料"
      description={data ? `共 ${data.over_limit} 项超上限（存量 > 上限）` : undefined}
    >
      {data ? (
        <Table
          rowKey={r => r._key}
          size="small"
          columns={columns}
          dataSource={withRowKeys(data.materials)}
          pagination={false}
          locale={{ emptyText: '无超储物料' }}
        />
      ) : (
        <DegradedSection domain="超储物料" />
      )}
    </SectionCard>
  )
}

function useOverviewData() {
  return useQuery({
    queryKey: ['safety', 'overview'],
    queryFn: fetchSafetyOverview,
  })
}

export function SafetyOverviewDashboard() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useOverviewData()
  const [openCell, setOpenCell] = useState<OverviewDigestCell | null>(null)

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['safety', 'overview'] })

  const hazards = data?.hazards
  const alarms = data?.alarms
  const trend = hazards?.trend
  const analysis = alarms?.analysis

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '总览驾驶舱']}
        title="安全总览驾驶舱"
        description="今日安全态势只读总览——隐患 / 作业 / 报警 / 证书 / 危化品 / 速递"
        actions={
          <Button icon={<RefreshCw size={14} />} onClick={refresh}>
            刷新
          </Button>
        }
      />

      {isError && (
        <div
          className="mb-3 rounded-lg px-4 py-2.5 text-[13px]"
          style={{ background: 'var(--wh-danger-bg)', color: 'var(--wh-expired)' }}
        >
          总览数据加载失败，请点击「刷新」重试（各域独立采集，单域故障不影响其他区块）。
        </div>
      )}
      {data && data.errors.length > 0 && (
        <div className="mb-3 rounded-lg bg-[var(--wh-warn-bg)] px-4 py-2 text-[12px] text-[var(--wh-warn)]">
          部分区块采集降级：{data.errors.join('；')}
        </div>
      )}

      <KpiSection data={data} loading={isLoading} />

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={14}>
          {/* h-full 打通百分比高度链：Col 等高拉伸 → 本列 definite → 图表卡 flex-1 分摊余高，
              卡内 height:100% 才能解析（echarts 否则回退 100px 小画布缩在卡顶） */}
          <div className="flex h-full flex-col gap-3">
            <DigestSection
              cells={data?.digest?.cells ?? null}
              degraded={Boolean(data && data.digest === null)}
              onOpenCell={setOpenCell}
            />
            <SectionCard
              title="隐患治理趋势"
              description="近 30 天新增 / 闭环"
              className="flex flex-1 flex-col"
              bodyClassName="flex-1 min-h-[240px]"
            >
              {trend ? (
                <TrendAreaChart
                  dates={trend.dates.map(d => d.slice(5))}
                  seriesA={trend.created}
                  seriesB={trend.closed}
                  labelA="新增"
                  labelB="闭环"
                  toneA="danger"
                  toneB="ok"
                  height="100%"
                  emptyText="近 30 天暂无隐患动态"
                />
              ) : (
                <Spin className="block w-full text-center" />
              )}
            </SectionCard>
            <SectionCard
              title="报警分析"
              description="近 7 日消防 / 中控按日计数"
              className="flex flex-1 flex-col"
              bodyClassName="flex-1 min-h-[240px]"
            >
              {analysis ? (
                <div className="flex h-full flex-col gap-2">
                  <div className="min-h-[180px] flex-1">
                    <TrendAreaChart
                      dates={analysis.dates.map(d => d.slice(5))}
                      seriesA={analysis.fire_daily}
                      seriesB={analysis.central_daily}
                      labelA="消防"
                      labelB="中控"
                      toneA="danger"
                      toneB="info"
                      height="100%"
                      emptyText="近 7 日暂无报警"
                    />
                  </div>
                  {analysis.top_fire_types.length > 0 && (
                    <div className="h-[120px]">
                      <div className="mb-1 px-1 text-[12px] text-[var(--color-stone)]">
                        Top 报警类型（近 7 日 · 消防口径）
                      </div>
                      <RankBarChart
                        names={analysis.top_fire_types.map(t => t.name)}
                        values={analysis.top_fire_types.map(t => t.count)}
                        height={100}
                        color={TONE_HEX.danger}
                        emptyText=""
                      />
                    </div>
                  )}
                </div>
              ) : (
                <Spin className="block w-full text-center" />
              )}
            </SectionCard>
          </div>
        </Col>
        <Col xs={24} xl={10}>
          <HealthWall health={data?.module_health ?? null} />
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={8}>
          <KeyRiskOpsTable data={data?.key_risk_ops ?? null} />
        </Col>
        <Col xs={24} xl={8}>
          <ExpiringCertsTable data={data?.certs ?? null} />
        </Col>
        <Col xs={24} xl={8}>
          <OverLimitTable data={data?.chemicals ?? null} />
        </Col>
      </Row>

      <Modal
        open={openCell !== null}
        title={openCell ? `${openCell.title} · ${data?.date ?? ''}` : ''}
        footer={null}
        width={720}
        onCancel={() => setOpenCell(null)}
      >
        {openCell && (
          <div className="max-h-[70vh] overflow-y-auto">
            <div className="mb-2">
              <Tag color="blue">{openCell.tag_text}</Tag>
              <span className="ml-2 text-[12px] text-[var(--color-steel)]">
                推送时间 {sentAtText(openCell.sent_at)}
              </span>
            </div>
            <MarkdownView
              text={[openCell.stats, openCell.zone, '---', openCell.detail]
                .filter(Boolean)
                .join('\n\n')}
            />
          </div>
        )}
      </Modal>
    </div>
  )
}
