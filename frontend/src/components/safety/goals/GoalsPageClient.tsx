'use client'

/**
 * 目标责任与绩效（S1）——体系标准符合性核查清单（2026-10-21 改造）。
 *
 * 标准（该做什么）× 运行数据（实际做了什么）= 四态判定：
 * 达标 / 进行中 / 未达标 / 无数据。纯只读监控——标准行在飞书多维表格
 * 「体系标准核查表」维护，操作在多维表格与机器人（3.0 口径）。
 * 证据下钻（凭据 Drawer）：达标可点验明细，无数据附原因；筛选/部门汇总
 * 分票交付（见 .scratch/s1-standard-compliance/issues）。
 */
import { useState } from 'react'
import { Drawer, Select, Table, Tabs } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck, DatabaseZap, History, TriangleAlert } from 'lucide-react'
import {
  fetchStandardCheckPage,
  fetchStandardEvidence,
  fetchStandardHistory,
  type StandardCheckData,
  type StandardCheckFilters,
  type StandardCheckStatus,
  type StandardDeptSummary,
  type StandardHistoryRow,
  type StandardRow,
  type StandardSnapshotStatus,
  type StandardSummary,
} from '@/lib/api/safety/standard-check'
import {
  EmptyGuide,
  PageHeader,
  SectionCard,
  StatCard,
  StatusTag,
} from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'

const STATUS_TAG: Record<StandardCheckStatus, { label: string; tone: Tone }> = {
  not_connected: { label: '未接入', tone: 'default' },
  live: { label: '已接入', tone: 'ok' },
  degraded: { label: '数据降级', tone: 'warn' },
}

const ROW_STATUS: Record<StandardRow['status'], { label: string; tone: Tone }> = {
  ok: { label: '达标', tone: 'ok' },
  in_progress: { label: '进行中', tone: 'info' },
  missed: { label: '未达标', tone: 'danger' },
  no_data: { label: '无数据', tone: 'default' },
}

// 定格六态（snapshot）：人工达标/未达标与自动项同色系，中期快照=进行中
const SNAP_STATUS: Record<StandardSnapshotStatus, { label: string; tone: Tone }> = {
  achieved: { label: '达标', tone: 'ok' },
  manual_done: { label: '达标·人工', tone: 'ok' },
  missed: { label: '未达标', tone: 'danger' },
  manual_missed: { label: '未达标·人工', tone: 'danger' },
  no_data: { label: '无数据', tone: 'default' },
  in_progress: { label: '进行中', tone: 'info' },
}

const STAT_CARDS: {
  key: keyof StandardSummary
  label: string
  tone: Tone
  unit?: string
}[] = [
  { key: 'ok', label: '达标', tone: 'ok' },
  { key: 'in_progress', label: '进行中', tone: 'info' },
  { key: 'missed', label: '未达标', tone: 'danger' },
  { key: 'no_data', label: '无数据', tone: 'default' },
  { key: 'compliance_rate', label: '综合符合率', tone: 'ok', unit: '%' },
]


function EvidenceDrawer({
  record,
  onClose,
}: {
  record: StandardRow | null
  onClose: () => void
}) {
  const query = useQuery({
    queryKey: ['standard-evidence', record?.record_id],
    queryFn: () => fetchStandardEvidence(record!.record_id),
    enabled: record !== null,
  })
  const data = query.data
  return (
    <Drawer
      title={record ? `${record.no} 凭据` : '凭据'}
      open={record !== null}
      onClose={onClose}
      width={480}
      destroyOnClose
    >
      {query.isLoading && <span style={{ fontSize: 13, color: '#a4a097' }}>取数中…</span>}
      {query.isError && <span style={{ fontSize: 13, color: '#c2410c' }}>取数失败，稍后重试</span>}
      {data && (
        <div className="space-y-3">
          <div style={{ fontSize: 13 }}>
            <div style={{ color: '#6b675e' }}>{data.clause}</div>
            {data.window && (
              <div style={{ marginTop: 4, color: '#a4a097', fontSize: 12 }}>
                核查窗口 {data.window.start} ~ {data.window.end}
              </div>
            )}
          </div>
          {data.evidence.length > 0 ? (
            <ul className="space-y-2" style={{ paddingLeft: 16, fontSize: 13 }}>
              {data.evidence.map((e, i) => (
                <li key={i}>
                  {e.url ? (
                    <a href={e.url} target="_blank" rel="noreferrer">
                      {e.title}
                    </a>
                  ) : (
                    e.title
                  )}
                  {e.date && (
                    <span style={{ marginLeft: 6, color: '#a4a097', fontSize: 12 }}>
                      {e.date}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <div
              style={{
                fontSize: 13,
                color: '#6b675e',
                background: '#f5f4f1',
                padding: '10px 12px',
                borderRadius: 8,
              }}
            >
              {data.no_data_reason || '该标准为人工核查项，请在多维表格勾选核查结果'}
            </div>
          )}
        </div>
      )}
    </Drawer>
  )
}

export default function GoalsPageClient() {
  const [evidenceRow, setEvidenceRow] = useState<StandardRow | null>(null)
    const openEvidence = (row: StandardRow) => setEvidenceRow(row)

    const columns: ColumnsType<StandardRow> = [
      {
        title: '凭据',
        key: 'evidence',
        width: 64,
        render: (_: unknown, row) =>
          row.auto || row.status === 'no_data' ? (
            <a onClick={() => openEvidence(row)} style={{ fontSize: 12 }}>
              查看
            </a>
          ) : (
            <span style={{ fontSize: 12, color: '#c9c5bc' }}>—</span>
          ),
      },
    { title: '编号', dataIndex: 'no', width: 90, fixed: 'left' },
    { title: '标准条款', dataIndex: 'clause', ellipsis: true },
    {
      title: '目标',
      dataIndex: 'target_display',
      width: 100,
      render: (v: string) => v || '—',
    },
    {
      title: '当前完成',
      dataIndex: 'actual_display',
      width: 110,
      render: (v: string | null, row) => {
        if (!v) return '—'
        if (row.status === 'in_progress' && row.residual_days !== null) {
          return (
            <span>
              {v}
              <span style={{ fontSize: 12, color: '#a4a097' }}>
                （距周期末 {row.residual_days} 天）
              </span>
            </span>
          )
        }
        return v
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (s: StandardRow['status']) => {
        const tag = ROW_STATUS[s]
        return <StatusTag label={tag.label} tone={tag.tone} />
      },
    },
    {
      title: '核查方式',
      dataIndex: 'auto',
      width: 100,
      render: (auto: boolean) =>
        auto ? (
          <span style={{ fontSize: 12, color: '#4b8a5a' }}>系统核查</span>
        ) : (
          <span style={{ fontSize: 12, color: '#a4a097' }}>人工勾选</span>
        ),
    },
    {
      title: '责任部门',
      dataIndex: 'department',
      width: 130,
      render: (v: string[]) => (v.length > 0 ? v.join('、') : '—'),
    },
    {
      title: '备注',
      dataIndex: 'note',
      width: 120,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
  ]
  const [filters, setFilters] = useState<StandardCheckFilters>({})
  const yearOptions = (() => {
    const y = new Date().getFullYear()
    return [y - 2, y - 1, y, y + 1].map((v) => ({ value: v, label: String(v) }))
  })()
  const query = useQuery({
    queryKey: ['standard-check', filters],
    queryFn: () => fetchStandardCheckPage(filters),
  })
  const data = query.data
  const status = data?.status
  const tag = status ? STATUS_TAG[status] : undefined
  const summary = status === 'live' ? data?.summary : null

  const emptyGuide = (() => {
    if (query.isError) {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据暂时不可用"
          description="页面数据加载失败，请稍后重试或联系管理员"
        />
      )
    }
    if (status === 'not_connected') {
      return (
        <EmptyGuide
          compact
          icon={<DatabaseZap size={28} />}
          title="暂无可核对的体系标准"
          description="在飞书多维表格建「体系标准核查表」并在 bitable 配置页登记 goals/standard_check 连接后，本页自动按标准清单逐条核对运行数据（55 条初版清单见设计文档附录 A）"
        />
      )
    }
    if (status === 'degraded') {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据源读取降级"
          description={(data?.errors ?? []).join('；') || '连接有效但读取失败，稍后自动恢复'}
        />
      )
    }
    return (
      <EmptyGuide
        compact
        title="当年无标准行"
        description="核查表里没有当前年度的标准行，请在多维表格补录或复制往年清单"
      />
    )
  })()

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '体系治理']}
        title="目标责任与绩效"
        description="体系标准符合性核查：目标·责任·绩效整理为可核查标准，对照系统运行数据自动判定达成情况"
        extra={tag ? <StatusTag label={tag.label} tone={tag.tone} /> : undefined}
      />

      {/* 统计行（四态计数 + 综合符合率；未接入显示「—」） */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {STAT_CARDS.map((card) => {
          const raw = summary?.[card.key]
          const value =
            summary && raw !== null && raw !== undefined
              ? `${raw}${card.unit ?? ''}`
              : '—'
          return (
            <StatCard
              key={card.key}
              label={card.label}
              value={value}
              tone={summary && raw !== null && raw !== undefined ? card.tone : 'default'}
              sub={card.key === 'compliance_rate' ? '达标/(达标+未达标)' : undefined}
              loading={query.isLoading}
            />
          )
        })}
      </div>

      {/* 筛选栏（要素/状态/部门；后端过滤） */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select
          allowClear
          placeholder="年度"
          style={{ width: 100 }}
          value={filters.year}
          onChange={(v) => setFilters((f) => ({ ...f, year: v }))}
          options={yearOptions}
        />
        <Select
          allowClear
          placeholder="要素归属"
          style={{ width: 170 }}
          value={filters.element}
          onChange={(v) => setFilters((f) => ({ ...f, element: v }))}
          options={(data?.groups ?? []).map((g) => ({
            value: g.element, label: g.element,
          }))}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 120 }}
          value={filters.status}
          onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
          options={[
            { value: 'ok', label: '达标' },
            { value: 'in_progress', label: '进行中' },
            { value: 'missed', label: '未达标' },
            { value: 'no_data', label: '无数据' },
          ]}
        />
        <Select
          allowClear
          placeholder="责任部门"
          style={{ width: 170 }}
          value={filters.department}
          onChange={(v) => setFilters((f) => ({ ...f, department: v }))}
          options={(data?.departments ?? []).map((d) => ({
            value: d.name, label: d.name,
          }))}
        />
      </div>

      <Tabs
        defaultActiveKey="list"
        items={[
          {
            key: 'list',
            label: `标准清单`,
            children: (
              <StandardListPanel
                data={data}
                loading={query.isLoading}
                emptyGuide={emptyGuide}
                columns={columns}
              />
            ),
          },
          {
            key: 'dept',
            label: '责任部门汇总',
            children: <DeptSummaryPanel departments={data?.departments ?? []} live={status === 'live'} />,
          },
          {
            key: 'history',
            label: '历史定格',
            children: <StandardHistoryPanel />,
          },
        ]}
      />


      <EvidenceDrawer record={evidenceRow} onClose={() => setEvidenceRow(null)} />
    </div>
  )
}

function StandardListPanel({
  data,
  loading,
  emptyGuide,
  columns,
}: {
  data: StandardCheckData | undefined
  loading: boolean
  emptyGuide: React.ReactNode
  columns: ColumnsType<StandardRow>
}) {
  return (
    <SectionCard
      title="标准核查清单"
      description="按 GB/T 33000-2016 八要素分组；标准行在飞书多维表格维护，平台只读判定不回写"
    >
      <div className="space-y-4">
        {(data?.groups ?? []).map((group) => (
          <div key={group.element}>
            <div
              className="mb-2 flex items-center gap-2"
              style={{ fontSize: 14, fontWeight: 600 }}
            >
              <ClipboardCheck size={16} style={{ color: '#4b8a5a' }} />
              {group.element}
              <span style={{ fontSize: 12, color: '#a4a097', fontWeight: 400 }}>
                {group.rows.length} 条
              </span>
            </div>
            <Table
              columns={columns}
              dataSource={group.rows}
              rowKey="record_id"
              size="small"
              loading={loading}
              scroll={{ x: 'max-content' }}
              pagination={false}
              locale={{ emptyText: emptyGuide }}
            />
          </div>
        ))}
        {(data?.groups ?? []).length === 0 && emptyGuide}
      </div>
    </SectionCard>
  )
}

function DeptSummaryPanel({
  departments,
  live,
}: {
  departments: StandardDeptSummary[]
  live: boolean
}) {
  const cols = [
    { title: '部门', dataIndex: 'name', width: 160 },
    { title: '名下标准', dataIndex: 'total', width: 90 },
    { title: '达标', dataIndex: 'ok', width: 80 },
    { title: '进行中', dataIndex: 'in_progress', width: 80 },
    { title: '未达标', dataIndex: 'missed', width: 80 },
    { title: '无数据', dataIndex: 'no_data', width: 80 },
  ]
  return (
    <SectionCard
      title="责任部门汇总"
      description="联合责任口径：一条标准挂多部门时计入每个部门；排名=未达标优先。责任的落点，不点名个人"
    >
      <Table
        columns={cols}
        dataSource={live ? departments : []}
        rowKey="name"
        size="small"
        pagination={false}
        locale={{
          emptyText: (
            <EmptyGuide compact title="暂无部门数据" description="核查表未接入或标准行未填责任部门" />
          ),
        }}
      />
    </SectionCard>
  )
}

function StandardHistoryPanel() {
  const [year, setYear] = useState<number>(new Date().getFullYear())
  const query = useQuery({
    queryKey: ['standard-history', year],
    queryFn: () => fetchStandardHistory(year),
  })
  const data = query.data
  const yearOptions = (() => {
    const current = new Date().getFullYear()
    const years = new Set<number>(data?.available_years ?? [])
    years.add(current)
    years.add(year)
    return [...years].sort((a, b) => b - a).map((v) => ({ value: v, label: String(v) }))
  })()

  const columns: ColumnsType<StandardHistoryRow> = [
    { title: '编号', dataIndex: 'standard_no', width: 90, fixed: 'left' },
    { title: '标准条款（定格快照）', dataIndex: 'clause', ellipsis: true },
    {
      title: '目标',
      dataIndex: 'target_display',
      width: 100,
      render: (v: string) => v || '—',
    },
    {
      title: '定格完成',
      dataIndex: 'actual_display',
      width: 110,
      render: (v: string | null) => v || '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (s: StandardSnapshotStatus) => {
        const tag = SNAP_STATUS[s]
        return <StatusTag label={tag.label} tone={tag.tone} />
      },
    },
    {
      title: '责任部门',
      dataIndex: 'department',
      width: 130,
      render: (v: string[]) => (v.length > 0 ? v.join('、') : '—'),
    },
    {
      title: '附注',
      dataIndex: 'note',
      width: 140,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
  ]

  const emptyGuide = query.isError ? (
    <EmptyGuide
      compact
      icon={<TriangleAlert size={28} />}
      title="数据暂时不可用"
      description="定格记录加载失败，请稍后重试"
    />
  ) : (
    <EmptyGuide
      compact
      icon={<History size={28} />}
      title={`${year} 年暂无定格记录`}
      description={
        (data?.available_years ?? []).length > 0
          ? `定格任务每季度首日 08:20 运行；可切换到有定格记录的年份（${data!.available_years.join('、')}）`
          : '定格任务每季度首日 08:20 自动定格上季度标准达成情况；首次定格前本页为空，属正常'
      }
    />
  )

  return (
    <SectionCard
      title="历史定格"
      description="周期末自动定格的达成留档（snapshot），迎检/自评直接取定格结果，不实时重算；清单后续修订不影响已定格历史"
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select
          placeholder="年份"
          style={{ width: 100 }}
          value={year}
          onChange={(v) => setYear(v)}
          options={yearOptions}
        />
      </div>
      <div className="space-y-4">
        {(data?.periods ?? []).map((period) => {
          const s = period.summary
          return (
            <div key={period.period_key}>
              <div
                className="mb-2 flex items-center gap-2"
                style={{ fontSize: 14, fontWeight: 600 }}
              >
                <History size={16} style={{ color: '#4b8a5a' }} />
                {period.label}
                <span style={{ fontSize: 12, color: '#a4a097', fontWeight: 400 }}>
                  定格于 {period.frozen_at.slice(0, 10)} · 达标 {s.achieved + s.manual_done}/
                  {s.achieved + s.manual_done + s.missed + s.manual_missed}
                  {s.compliance_rate !== null && ` · 符合率 ${s.compliance_rate}%`}
                  {s.no_data > 0 && ` · 无数据 ${s.no_data}`}
                  {s.in_progress > 0 && ` · 进行中 ${s.in_progress}`}
                </span>
              </div>
              <Table
                columns={columns}
                dataSource={period.rows}
                rowKey={(r) => `${period.period_key}-${r.standard_no}`}
                size="small"
                loading={query.isLoading}
                scroll={{ x: 'max-content' }}
                pagination={false}
              />
            </div>
          )
        })}
        {!query.isLoading && (data?.periods ?? []).length === 0 && emptyGuide}
      </div>
    </SectionCard>
  )
}
