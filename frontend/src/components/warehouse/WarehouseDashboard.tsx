'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Col, Row, Spin } from 'antd'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ClipboardList,
  Inbox,
  Package,
  RefreshCw,
  Send,
} from 'lucide-react'
import {
  fetchDashboardSummaryClient,
  fetchDashboardTodosClient,
  fetchLowStockTopClient,
  fetchMovementTrendClient,
  fetchStockDistributionClient,
} from '@/lib/api/warehouse'
import {
  MATERIAL_CATEGORY_LABEL,
  type DashboardSummary,
  type DashboardTodos,
  type LowStockTop,
  type MovementTrendPoint,
  type StockDistribution,
} from '@/types/warehouse'
import { PageHeader } from './PageHeader'
import { SectionCard } from './ui/SectionCard'
import { StatCard, StatDelta } from './ui/StatCard'
import { StatusTag } from './ui/StatusTag'
import { TONE_HEX, type Tone } from './ui/tokens'
import { Button } from 'antd'
import { DonutChart, RankBarChart, TrendAreaChart } from './ui/charts'

const LOCATION_TYPE_LABEL: Record<string, string> = {
  normal: '常温',
  cold: '冷藏',
  danger: '危险品',
}

function categoryLabel(key: string): string {
  return MATERIAL_CATEGORY_LABEL[key as keyof typeof MATERIAL_CATEGORY_LABEL] ?? key
}

/** 异常汇总条：有待处理事项时首屏置顶提示（异常先行原则） */
function PendingBanner({ summary }: { summary: DashboardSummary | undefined }) {
  const router = useRouter()
  if (!summary) return null
  const items: { label: string; count: number; path: string; tone: 'danger' | 'warn' }[] = []
  if (summary.low_stock_count > 0) {
    items.push({ label: '低库存', count: summary.low_stock_count, path: '/warehouse/intelligence', tone: 'danger' })
  }
  if (summary.draft_stocktake_count > 0) {
    items.push({ label: '进行中盘点', count: summary.draft_stocktake_count, path: '/warehouse/stocktake', tone: 'warn' })
  }
  if (items.length === 0) return null
  const total = items.reduce((acc, it) => acc + it.count, 0)
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-4 py-2.5 text-[13px]"
      style={{ background: 'var(--wh-danger-bg)', color: 'var(--wh-expired)' }}
    >
      <span className="inline-flex items-center gap-1.5 font-medium">
        <AlertTriangle size={15} />
        {total} 项待处理：
      </span>
      {items.map(it => (
        <button
          key={it.label}
          type="button"
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-full bg-white/70 px-2.5 py-0.5 hover:bg-white"
          onClick={() => router.push(it.path)}
        >
          <StatusTag tone={it.tone} label={it.label} />
          <b className="tabular-nums">{it.count}</b>
        </button>
      ))}
      <button
        type="button"
        className="ml-auto inline-flex cursor-pointer items-center gap-0.5 border-0 bg-transparent p-0 hover:underline"
        style={{ color: 'inherit' }}
        onClick={() => router.push(items[0].path)}
      >
        去处理 <ArrowUpRight size={14} />
      </button>
    </div>
  )
}

function KpiRow({ summary, loading }: { summary: DashboardSummary | undefined; loading: boolean }) {
  const router = useRouter()
  const change = summary?.total_quantity_change
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} sm={12} xl={5}>
        <StatCard
          emphasized
          label="库存总量"
          tone="primary"
          icon={<Package />}
          loading={loading}
          value={(summary?.total_quantity ?? 0).toFixed(2)}
          sub={
            change === null || change === undefined ? (
              '快照积累中'
            ) : (
              <span>
                较昨日 <StatDelta value={change} />
              </span>
            )
          }
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="今日入库"
          tone="ok"
          icon={<Inbox />}
          loading={loading}
          value={(summary?.today_inbound_quantity ?? 0).toFixed(2)}
          sub={`${summary?.today_inbound_count ?? 0} 笔`}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="今日出库"
          tone="danger"
          icon={<Send />}
          loading={loading}
          value={(summary?.today_outbound_quantity ?? 0).toFixed(2)}
          sub={`${summary?.today_outbound_count ?? 0} 笔`}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="低库存项"
          tone={summary && summary.low_stock_count > 0 ? 'danger' : 'default'}
          icon={<AlertTriangle />}
          loading={loading}
          value={summary?.low_stock_count ?? 0}
          onClick={() => router.push('/warehouse/intelligence')}
        />
      </Col>
      <Col xs={12} xl={4}>
        <StatCard
          label="进行中盘点"
          tone="info"
          icon={<ClipboardList />}
          loading={loading}
          value={summary?.draft_stocktake_count ?? 0}
          onClick={() => router.push('/warehouse/stocktake')}
        />
      </Col>
      <Col xs={12} xl={3}>
        <StatCard
          label="库存 SKU"
          tone="default"
          icon={<Package />}
          loading={loading}
          value={summary?.stock_sku_count ?? 0}
          onClick={() => router.push('/warehouse/inventory')}
        />
      </Col>
    </Row>
  )
}

/** 右栏可点击行项（名称+右侧数据，hover 强调）；tagLabel 缺省时按 入/出/调 映射 */
function FeedRow({
  title,
  right,
  tag,
  tagLabel,
  onClick,
}: {
  title: string
  right: string
  tag?: Tone
  tagLabel?: string
  onClick?: () => void
}) {
  const label = tagLabel ?? (tag === 'ok' ? '入' : tag === 'danger' ? '出' : '调')
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-2 py-2 text-left transition-colors hover:bg-[var(--color-surface)]"
    >
      {tag && <StatusTag tone={tag} label={label} />}
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--color-charcoal)]">{title}</span>
      <span className="shrink-0 text-[12px] tabular-nums text-[var(--color-steel)]">{right}</span>
    </button>
  )
}

function FeedGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 px-2 text-[12px] font-medium uppercase tracking-wide text-[var(--color-stone)]">
        {title}
      </div>
      <div className="-mx-1 flex flex-col">{children}</div>
    </div>
  )
}

/** QC 待办阶段 → FeedRow 标签色调（待取样/待出报最紧迫，待放行流程已推进） */
const QC_STAGE_TONE: Record<string, Tone> = {
  待取样: 'warn',
  待出报: 'warn',
  待放行: 'ok',
}

function TodosPanel({ data, loading }: { data: DashboardTodos | undefined; loading: boolean }) {
  const router = useRouter()
  if (loading) return <Spin className="block w-full text-center" />
  if (!data) return null
  const qc = data.qc_pending
  return (
    <div className="flex flex-col gap-4">
      {qc && (
        <FeedGroup
          title={`QC 闭环待检（待取样 ${qc.await_sample_count} · 待出报 ${qc.await_report_count} · 待放行 ${qc.await_release_count}）`}
        >
          {qc.items.length === 0 && (
            <div className="px-2 py-1 text-[13px] text-[var(--color-stone)]">暂无待检/待放行批次</div>
          )}
          {qc.items.map(item => (
            <FeedRow
              key={`${item.batch_no}-${item.stage}`}
              title={`${item.material_name}（${item.batch_no}）`}
              right={item.receipt_date ?? '-'}
              tag={QC_STAGE_TONE[item.stage] ?? 'warn'}
              tagLabel={item.stage}
              onClick={() => router.push(`/warehouse/inventory?keyword=${encodeURIComponent(item.batch_no)}`)}
            />
          ))}
        </FeedGroup>
      )}
      <FeedGroup title="低库存（前 5）">
        {data.low_stock_items.length === 0 && (
          <div className="px-2 py-1 text-[13px] text-[var(--color-stone)]">暂无低库存物料</div>
        )}
        {data.low_stock_items.map(item => (
          <FeedRow
            key={item.material_code}
            title={item.material_name}
            right={`${item.total_quantity} / 安全 ${item.safety_stock}`}
            tag="warn"
            tagLabel="低库存"
            onClick={() => router.push(`/warehouse/inventory?keyword=${encodeURIComponent(item.material_code)}`)}
          />
        ))}
      </FeedGroup>
      <FeedGroup title="进行中盘点">
        {data.draft_stocktakes.length === 0 && (
          <div className="px-2 py-1 text-[13px] text-[var(--color-stone)]">暂无草稿盘点单</div>
        )}
        {data.draft_stocktakes.map(item => (
          <FeedRow
            key={item.stocktake_no}
            title={item.stocktake_no}
            right={item.remark ?? '-'}
            onClick={() => router.push('/warehouse/stocktake')}
          />
        ))}
      </FeedGroup>
      <FeedGroup title="最近出入库">
        {data.recent_movements.length === 0 && (
          <div className="px-2 py-1 text-[13px] text-[var(--color-stone)]">暂无出入库记录</div>
        )}
        {data.recent_movements.map((item, i) => (
          <FeedRow
            key={`${item.movement_no}-${i}`}
            title={`${item.material_name} × ${item.quantity}${item.unit}`}
            right={new Date(item.occurred_at).toLocaleDateString('zh-CN')}
            tag={item.direction === 'inbound' ? 'ok' : item.direction === 'outbound' ? 'danger' : 'warn'}
            onClick={() => router.push('/warehouse/inout')}
          />
        ))}
      </FeedGroup>
    </div>
  )
}

export function WarehouseDashboard() {
  const router = useRouter()
  const queryClient = useQueryClient()

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'summary'],
    queryFn: fetchDashboardSummaryClient,
  })
  const { data: trend } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'trend'],
    queryFn: () => fetchMovementTrendClient(30),
  })
  const { data: distribution } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'distribution'],
    queryFn: fetchStockDistributionClient,
  })
  const { data: lowStockTop } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'low-stock-top'],
    queryFn: () => fetchLowStockTopClient(10),
  })
  const { data: todos, isLoading: todosLoading } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'todos'],
    queryFn: fetchDashboardTodosClient,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['warehouse', 'dashboard'] })

  const drillToInventory = (keyword: string) => {
    if (keyword) router.push(`/warehouse/inventory?keyword=${encodeURIComponent(keyword)}`)
  }

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '驾驶舱']}
        title="仓储驾驶舱"
        description="库存总览、出入库趋势、分布与待办"
        actions={
          <Button icon={<RefreshCw size={14} />} onClick={refresh}>
            刷新
          </Button>
        }
      />

      <PendingBanner summary={summary} />
      <KpiRow summary={summary} loading={summaryLoading} />

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={16}>
          <SectionCard
            title="出入库趋势"
            description="近 30 天入库 / 出库数量"
            className="flex h-full flex-col"
            bodyClassName="flex-1 min-h-[260px]"
          >
            {trend ? (
              <TrendAreaChart
                dates={trend.map(p => p.date.slice(5))}
                inbound={trend.map(p => p.inbound)}
                outbound={trend.map(p => p.outbound)}
                height="100%"
              />
            ) : (
              <Spin className="block w-full text-center" />
            )}
          </SectionCard>
        </Col>
        <Col xs={24} xl={8}>
          <SectionCard
            title="待办与预警"
            description="点击条目可直接下钻"
            className="flex h-full flex-col"
            bodyClassName="flex-1"
          >
            <TodosPanel data={todos} loading={todosLoading} />
          </SectionCard>
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={12}>
          <SectionCard
            title="库存分布"
            description="按物料分类"
            className="h-full"
          >
            {distribution ? (
              <DonutChart
                items={distribution.by_category.map(item => ({
                  name: categoryLabel(item.category),
                  value: item.total_quantity,
                }))}
                centerLabel="库存总量"
              />
            ) : (
              <Spin className="block w-full text-center" />
            )}
          </SectionCard>
        </Col>
        <Col xs={24} xl={12}>
          <SectionCard
            title="库位类型分布"
            description="各类型库位的库存量"
            className="h-full"
          >
            {distribution ? (
              <RankBarChart
                names={distribution.by_location_type.map(
                  item => LOCATION_TYPE_LABEL[item.location_type] ?? item.location_type,
                )}
                values={distribution.by_location_type.map(item => item.total_quantity)}
                emptyText="暂无库位库存"
              />
            ) : (
              <Spin className="block w-full text-center" />
            )}
          </SectionCard>
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={12}>
          <SectionCard title="低库存 Top10" description="库存低于安全库存，点击下钻明细">
            {lowStockTop ? (
              <RankBarChart
                names={lowStockTop.low_stock.map(i => i.material_name)}
                values={lowStockTop.low_stock.map(i => i.total_quantity)}
                color={TONE_HEX.danger}
                onPick={drillToInventory}
                emptyText="暂无低库存物料"
              />
            ) : (
              <Spin className="block w-full text-center" />
            )}
          </SectionCard>
        </Col>
        <Col xs={24} xl={12}>
          <SectionCard title="呆滞 Top10" description="90 天无入库，点击下钻明细">
            {lowStockTop ? (
              <RankBarChart
                names={lowStockTop.idle.map(i => i.material_name)}
                values={lowStockTop.idle.map(i => i.total_quantity)}
                color={TONE_HEX.warn}
                onPick={drillToInventory}
                emptyText="暂无呆滞物料"
              />
            ) : (
              <Spin className="block w-full text-center" />
            )}
          </SectionCard>
        </Col>
      </Row>
    </div>
  )
}
