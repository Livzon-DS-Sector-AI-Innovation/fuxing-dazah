'use client'

/**
 * EHS 变更管理台账（只读监控视图，3.0 口径）
 * 保留：台账查询、KPI 统计、AI 审核结论展示、详情查看（含跳飞书原文）。
 * 去除：全部平台状态机操作（新建/编辑/提交/审批/验收流转）——
 * 业务操作在飞书多维表格与机器人，Web 只读（状态机生产从未启用）。
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Button, Drawer, Input, Select, Space, Table, Tooltip } from 'antd'
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchEhsChanges, fetchEhsChangeStats } from '@/lib/api/safety/ehs-change'
import { CHANGE_DURATION_OPTIONS, CHANGE_TYPE_OPTIONS } from '@/types/safety'
import type { EhsChange } from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import { T, monoFont } from '../shared-styles'
import {
  AI_CONCLUSION_FILTER,
  CHANGE_DURATION_LABEL,
  CHANGE_TYPE_LABEL,
  STATUS_FILTER,
  getAiConclusion,
} from './ehsChangeConstants'
import { EhsChangeDetail, GradePill, StatusPill, AiConclusionPill } from './shared'

const LEDGER_STATS = { total: 0, status: {}, ai: { 审核通过: 0, 需补充完善: 0, 审核不通过: 0 } } as { total: number; status: Record<string, number>; ai: Record<string, number> }

export function EhsChangeLedgerPage() {
  const routerSearch = useSearchParams()

  const [filters, setFilters] = useState({
    status: undefined as string | undefined,
    change_type: undefined as string | undefined,
    change_grade: undefined as string | undefined,
    change_duration: undefined as string | undefined,
    keyword: routerSearch.get('keyword') ?? undefined,
    ai_review_conclusion: undefined as string | undefined,
  })
  const [pagination, setPagination] = useState({ page: 1, page_size: 20 })

  // Detail drawer
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedChange, setSelectedChange] = useState<EhsChange | null>(null)

  const queryClient = useQueryClient()

  const { ai_review_conclusion, ...serverFilters } = filters

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['ehs-changes'] })
    queryClient.invalidateQueries({ queryKey: ['ehs-change-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['ehs-change-stats', 'approval'],
    queryFn: () => fetchEhsChangeStats('approval'),
  })
  const stats = statsQuery.data ?? LEDGER_STATS

  // 列表 query（服务端筛选）
  const { data: listData, isLoading } = useQuery({
    queryKey: ['ehs-changes', { page: pagination.page, pageSize: pagination.page_size, serverFilters, feishuTableId: 'approval' }],
    queryFn: () => fetchEhsChanges({
      page: pagination.page,
      page_size: pagination.page_size,
      feishu_table_id: 'approval',
      sort_by: 'change_no',
      sort_order: 'desc',
      ...serverFilters,
    }),
  })

  // ai_review_conclusion 客户端过滤（保持原行为）
  const changes = useMemo(() => {
    const items = listData?.items ?? []
    if (ai_review_conclusion) {
      return items.filter((c) => getAiConclusion(c) === ai_review_conclusion)
    }
    return items
  }, [listData?.items, ai_review_conclusion])

  const total = listData?.total ?? 0

  const setKeywordFilter = (kw: string) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, keyword: kw || undefined }))
  }

  const setFilter = (patch: Record<string, string | undefined>) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, ...patch }))
  }

  // ── 统计卡带（ui-kit StatCard，点击联动筛选；选中卡片高亮为 primary）──
  const kpiCards = useMemo<
    { label: string; value: number; tone: Tone; active: boolean; onClick: () => void }[]
  >(
    () => [
      {
        label: '全部变更',
        value: stats.total,
        tone: 'default',
        active: !filters.status && !filters.ai_review_conclusion,
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: undefined }),
      },
      {
        label: '审批中',
        value: stats.status.under_review ?? 0,
        tone: 'info',
        active: filters.status === 'under_review',
        onClick: () => setFilter({ status: 'under_review', ai_review_conclusion: undefined }),
      },
      {
        label: '已通过',
        value: stats.status.approved ?? 0,
        tone: 'ok',
        active: filters.status === 'approved',
        onClick: () => setFilter({ status: 'approved', ai_review_conclusion: undefined }),
      },
      {
        label: '需补充完善',
        value: stats.ai['需补充完善'] ?? 0,
        tone: 'warn',
        active: filters.ai_review_conclusion === '需补充完善',
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: '需补充完善' }),
      },
      {
        label: '审核不通过',
        value: stats.ai['审核不通过'] ?? 0,
        tone: 'danger',
        active: filters.ai_review_conclusion === '审核不通过',
        onClick: () => setFilter({ status: undefined, ai_review_conclusion: '审核不通过' }),
      },
      {
        label: '已拒绝',
        value: stats.status.rejected ?? 0,
        tone: 'danger',
        active: filters.status === 'rejected',
        onClick: () => setFilter({ status: 'rejected', ai_review_conclusion: undefined }),
      },
    ],
    [stats, filters],
  )

  const cellText: React.CSSProperties = { fontSize: 12, color: T.slate }
  const cellEmpty: React.CSSProperties = { fontSize: 12, color: T.muted }

  const columns = [
    { title: '变更编号', dataIndex: 'change_no', width: 140,
      render: (_: string, record: EhsChange) => (
        <a
          onClick={() => { setSelectedChange(record); setDrawerOpen(true) }}
          style={{ color: '#0075de', textDecoration: 'none' }}
          onMouseEnter={(e) => { e.currentTarget.style.textDecoration = 'underline' }}
          onMouseLeave={(e) => { e.currentTarget.style.textDecoration = 'none' }}
        >
          <span style={monoFont}>{record.bt_change_no || record.change_no}</span>
        </a>
      ),
    },
    {
      title: '变更名称',
      dataIndex: 'title',
      ellipsis: true,
      render: (v: string) => (v ? <span style={{ fontSize: 13, color: T.charcoal }}>{v}</span> : <span style={cellEmpty}>—</span>),
    },
    {
      title: '变更分类',
      dataIndex: 'change_type',
      width: 104,
      render: (v: string | null) => (v ? <span style={cellText}>{CHANGE_TYPE_LABEL[v] || v}</span> : <span style={cellEmpty}>—</span>),
    },
    { title: '变更等级', dataIndex: 'change_grade', width: 88, render: (_: string, r: EhsChange) => <GradePill grade={r.change_grade} /> },
    {
      title: '变更时效',
      dataIndex: 'change_duration',
      width: 80,
      render: (v: string | null) => (v ? <span style={cellText}>{CHANGE_DURATION_LABEL[v] || v}</span> : <span style={cellEmpty}>—</span>),
    },
    { title: '申请部门', dataIndex: 'department', width: 108, ellipsis: true, render: (v: string) => (v ? <span style={cellText}>{v}</span> : <span style={cellEmpty}>—</span>) },
    { title: 'AI审核', dataIndex: 'ai_review_status', width: 88, render: (_: string, r: EhsChange) => <AiConclusionPill change={r} /> },
    { title: '状态', dataIndex: 'status', width: 78, render: (v: string) => <StatusPill status={v} /> },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      fixed: 'right' as const,
      render: (_: unknown, record: EhsChange) => (
        <Tooltip title="查看详情">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setSelectedChange(record); setDrawerOpen(true) }}>详情</Button>
        </Tooltip>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页头 */}
      <PageHeader
        breadcrumb={['安全管理', 'EHS 变更管理']}
        title="EHS 变更管理"
        description="EHS 变更申请（URS）与验收台账"
        actions={<Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>}
      />

      {/* 统计卡带（点击联动筛选） */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {kpiCards.map((k) => (
          <StatCard key={k.label} label={k.label} value={k.value} tone={k.active ? 'primary' : k.tone} onClick={k.onClick} />
        ))}
      </div>

      {/* 变更台账（筛选栏并入卡内） */}
      <SectionCard
        title="变更台账"
        description={`URS 申请与验收记录（共 ${total} 条）· 业务操作在飞书多维表格与机器人`}
      >
        <div style={{ marginBottom: 12 }}>
          <Space wrap>
            <Select placeholder="全部分类" allowClear size="small" style={{ width: 140 }} options={CHANGE_TYPE_OPTIONS} value={filters.change_type}
              onChange={(v) => setFilter({ change_type: v })} />
            <Select placeholder="全部时效" allowClear size="small" style={{ width: 120 }} options={CHANGE_DURATION_OPTIONS} value={filters.change_duration}
              onChange={(v) => setFilter({ change_duration: v })} />
            <Select placeholder="全部结论" allowClear size="small" style={{ width: 140 }} options={AI_CONCLUSION_FILTER} value={filters.ai_review_conclusion}
              onChange={(v) => setFilter({ ai_review_conclusion: v })} />
            <Select placeholder="全部状态" allowClear size="small" style={{ width: 120 }} options={STATUS_FILTER} value={filters.status}
              onChange={(v) => setFilter({ status: v })} />
            <Input.Search placeholder="搜索标题/编号" allowClear size="small" style={{ width: 220 }}
              defaultValue={filters.keyword}
              onSearch={(v) => setKeywordFilter(v)} />
          </Space>
        </div>
        <Table
          columns={columns}
          dataSource={changes}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: (
            <EmptyGuide compact title="暂无变更记录" description="调整筛选条件，或等待飞书多维表格同步后刷新" />
          ) }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => setPagination((p) => ({ ...p, page, page_size: pageSize })),
          }}
        />
      </SectionCard>

      {/* 详情 Drawer（只读） */}
      <Drawer
        title={selectedChange ? `变更详情 - ${selectedChange.bt_change_no || selectedChange.change_no}` : '变更详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedChange(null) }}
        width={820}
      >
        {selectedChange && (
          <EhsChangeDetail change={selectedChange} />
        )}
      </Drawer>
    </div>
  )
}
