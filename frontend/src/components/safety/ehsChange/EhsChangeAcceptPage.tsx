'use client'

/**
 * EHS 变更验收台账（验收页）
 * 突出验收信息（验收日期/验收意见）与关联追溯（跳回申请页搜索原审批）。
 * 视觉：DESIGN 统计卡 + 台账风格。
 */
import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Button,
  Drawer,
  Input,
  Select,
  Space,
  Table,
  Tooltip,
  Typography,
} from 'antd'
import { EyeOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchEhsChanges, fetchEhsChangeStats } from '@/lib/api/safety/ehs-change'
import type { EhsChange } from '@/types/safety'
import { T, monoFont } from '../shared-styles'
import {
  STATUS_FILTER,
  extractRelatedApprovalNo,
} from './ehsChangeConstants'
import {
  CARD_STYLE,
  EhsChangeDetail,
  GradePill,
  KpiCard,
  StatusPill,
} from './shared'

const { Title, Text, Paragraph } = Typography

const EMPTY_ACCEPT_STATS = { total: 0, status: {} } as { total: number; status: Record<string, number> }

export function EhsChangeAcceptPage() {
  const router = useRouter()

  const [filters, setFilters] = useState({
    status: undefined as string | undefined,
    change_grade: undefined as string | undefined,
    keyword: undefined as string | undefined,
  })
  const [pagination, setPagination] = useState({ page: 1, page_size: 20 })

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedChange, setSelectedChange] = useState<EhsChange | null>(null)

  const queryClient = useQueryClient()

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['ehs-change-stats', 'acceptance'],
    queryFn: () => fetchEhsChangeStats('acceptance'),
  })
  const stats = statsQuery.data ?? EMPTY_ACCEPT_STATS

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['ehs-changes', { page: pagination.page, pageSize: pagination.page_size, filters, feishuTableId: 'acceptance' }],
    queryFn: () => fetchEhsChanges({
      page: pagination.page,
      page_size: pagination.page_size,
      feishu_table_id: 'acceptance',
      sort_by: 'acceptance_date',
      sort_order: 'desc',
      ...filters,
    }),
  })
  const changes = listData?.items ?? []
  const total = listData?.total ?? 0

  const setFilter = (patch: Record<string, string | undefined>) => {
    setPagination((p) => ({ ...p, page: 1 }))
    setFilters((f) => ({ ...f, ...patch }))
  }

  // ── 关联追溯：跳回申请页并按编号自动搜索 ──
  const traceToApply = (relatedApproval: string | undefined) => {
    const no = extractRelatedApprovalNo(relatedApproval)
    if (!no) return
    router.push(`/safety/ehs-change/apply?keyword=${encodeURIComponent(no)}`)
  }

  const kpiCards = useMemo(
    () => [
      {
        label: '全部验收',
        value: stats.total,
        active: !filters.status,
        onClick: () => setFilter({ status: undefined }),
      },
      {
        label: '已通过',
        value: stats.status.approved ?? 0,
        color: T.success,
        active: filters.status === 'approved',
        onClick: () => setFilter({ status: 'approved' }),
      },
      {
        label: '审批中',
        value: stats.status.under_review ?? 0,
        color: T.warning,
        active: filters.status === 'under_review',
        onClick: () => setFilter({ status: 'under_review' }),
      },
      {
        label: '已拒绝',
        value: stats.status.rejected ?? 0,
        color: T.error,
        active: filters.status === 'rejected',
        onClick: () => setFilter({ status: 'rejected' }),
      },
      {
        label: '已取消',
        value: stats.status.closed ?? 0,
        color: T.steel,
        active: filters.status === 'closed',
        onClick: () => setFilter({ status: 'closed' }),
      },
    ],
    [stats, filters],
  )

  const cellText: React.CSSProperties = { fontSize: 12, color: T.slate }
  const cellEmpty: React.CSSProperties = { fontSize: 12, color: T.muted }

  const columns = [
    {
      title: '验收编号',
      dataIndex: 'change_no',
      width: 130,
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
    { title: '变更级别', dataIndex: 'change_grade', width: 88, render: (_: string, r: EhsChange) => <GradePill grade={r.change_grade} /> },
    { title: '发起人部门', dataIndex: 'department', width: 108, ellipsis: true, render: (v: string) => (v ? <span style={cellText}>{v}</span> : <span style={cellEmpty}>—</span>) },
    {
      title: '验收日期',
      dataIndex: 'bt_extra',
      width: 104,
      render: (_: unknown, r: EhsChange) =>
        r.bt_extra?.acceptance_date
          ? <span style={cellText}>{new Date(r.bt_extra.acceptance_date).toLocaleDateString('zh-CN')}</span>
          : <span style={cellEmpty}>—</span>,
    },
    {
      title: '验收意见',
      dataIndex: 'bt_acceptance_comment',
      ellipsis: true,
      render: (v: string) => (v ? <span style={cellText}>{v}</span> : <span style={cellEmpty}>—</span>),
    },
    {
      title: '关联审批',
      dataIndex: 'bt_extra',
      width: 200,
      render: (_: unknown, r: EhsChange) => {
        const no = extractRelatedApprovalNo(r.bt_extra?.related_approval)
        if (!no) return <span style={cellEmpty}>—</span>
        return (
          <Tooltip title={`查看原变更申请：${r.bt_extra?.related_approval}`}>
            <a onClick={() => traceToApply(r.bt_extra?.related_approval)} style={{ color: '#0075de', display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'none' }}>
              <LinkOutlined style={{ fontSize: 12 }} />
              <span style={monoFont}>{no}</span>
            </a>
          </Tooltip>
        )
      },
    },
    { title: '状态', dataIndex: 'status', width: 78, render: (v: string) => <StatusPill status={v} /> },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      fixed: 'right' as const,
      render: (_: unknown, record: EhsChange) => (
        <Tooltip title="查看验收详情">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setSelectedChange(record); setDrawerOpen(true) }}>详情</Button>
        </Tooltip>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 22, fontWeight: 600, color: T.ink }}>
            EHS变更验收
          </Title>
          <Text style={{ fontSize: 13, color: T.slate }}>
            数据来自飞书变更验收表 · 记录关联追溯至原变更申请
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => {
          queryClient.invalidateQueries({ queryKey: ['ehs-changes'] })
          queryClient.invalidateQueries({ queryKey: ['ehs-change-stats'] })
        }}>刷新</Button>
      </div>

      {/* KPI 卡带 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {kpiCards.map((k) => (
          <KpiCard key={k.label} label={k.label} value={k.value} active={k.active} color={k.color} onClick={k.onClick} />
        ))}
      </div>

      {/* 表格卡（筛选栏并入卡头） */}
      <div style={{ ...CARD_STYLE, padding: '4px 16px 12px' }}>
        <div style={{ margin: '0 -16px', padding: '8px 16px 12px', borderBottom: `1px solid ${T.hairlineSoft}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <Space wrap>
            <Select placeholder="全部级别" allowClear size="small" style={{ width: 120 }}
              options={[{ value: '', label: '全部级别' }, { value: 'major', label: '重大变更' }, { value: 'general', label: '一般变更' }]}
              value={filters.change_grade} onChange={(v) => setFilter({ change_grade: v })} />
            <Select placeholder="全部状态" allowClear size="small" style={{ width: 120 }} options={STATUS_FILTER} value={filters.status}
              onChange={(v) => setFilter({ status: v })} />
            <Input.Search placeholder="搜索变更名称/编号" allowClear size="small" style={{ width: 220 }}
              onSearch={(v) => setFilter({ keyword: v || undefined })} />
          </Space>
          <span style={{ fontSize: 12, color: T.steel }}>共 {total} 条</span>
        </div>
        <Table
          columns={columns}
          dataSource={changes}
          rowKey="id"
          loading={isLoading}
          size="small"
          style={{ marginTop: 8 }}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => setPagination((p) => ({ ...p, page, page_size: pageSize })),
          }}
        />
      </div>

      {/* 详情 Drawer */}
      <Drawer
        title={selectedChange ? `验收详情 - ${selectedChange.bt_change_no || selectedChange.change_no}` : '验收详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedChange(null) }}
        width={820}
      >
        {selectedChange && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* 关联追溯块 */}
            {selectedChange.bt_extra?.related_approval && (
              <div style={{ ...CARD_STYLE, padding: '12px 16px' }}>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>关联变更申请</Text>
                <Paragraph style={{ margin: 0, fontSize: 13, color: T.charcoal }}>
                  {selectedChange.bt_extra.related_approval}
                </Paragraph>
                <Button size="small" type="link" style={{ padding: 0, marginTop: 4, color: '#0075de' }}
                  icon={<LinkOutlined />}
                  onClick={() => traceToApply(selectedChange.bt_extra?.related_approval)}>
                  在变更申请中查看
                </Button>
              </div>
            )}
            <EhsChangeDetail change={selectedChange} onRefresh={() => queryClient.invalidateQueries({ queryKey: ['ehs-changes'] })} table="acceptance" />
          </div>
        )}
      </Drawer>
    </div>
  )
}
