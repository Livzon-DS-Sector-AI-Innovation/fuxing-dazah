'use client'

// 离职办理看板：办结单列表 + 发起入口 + 办理抽屉。
// 与「离职台账」页签并列——台账是结果数据，这里是过程流水线。
// 页头统计可以直接点：点到哪个阶段，列表就筛到哪个阶段（临期同理）。

import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, DatePicker, Input, Select, Space, Statistic, Table, Tag, Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import {
  fetchDepartmentsAction,
  fetchOffboardingCaseStats,
  fetchOffboardingCases,
} from '@/actions/hr'
import { useDebouncedCallback, useHasPermission } from '@/hooks/hr'
import {
  DEPARTURE_TYPE_TAG_COLORS,
  OFFBOARDING_STATUS_LABELS,
  OFFBOARDING_STATUS_TAG_COLORS,
} from '@/lib/hr'
import type { OffboardingCase, OffboardingCaseStats, OffboardingCaseStatus } from '@/types/hr'
import PageHeader from './PageHeader'
import OffboardingCaseDrawer from './OffboardingCaseDrawer'
import OffboardingNewCaseModal from './OffboardingNewCaseModal'
import { daysUntil } from './offboarding/CasePanel'

const STATUS_OPTIONS = (
  ['draft', 'approving', 'clearing', 'cert_issuing', 'delivering', 'signed', 'closed', 'canceled'] as const
).map((status) => ({ value: status, label: OFFBOARDING_STATUS_LABELS[status] }))

type Range = [Dayjs | null, Dayjs | null] | null

export default function OffboardingBoardClient() {
  // 水合安全的权限判断：本页在 Suspense 边界内，直接读权限 store 首帧会与 SSR 输出对不上
  const canManage = useHasPermission('hr:departure:manage')

  const [cases, setCases] = useState<OffboardingCase[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<OffboardingCaseStatus | ''>('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [department, setDepartment] = useState('')
  const [range, setRange] = useState<Range>(null)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [stats, setStats] = useState<OffboardingCaseStats | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await fetchOffboardingCases({
        status: status || undefined,
        department: department || undefined,
        keyword: keyword || undefined,
        date_from: range?.[0]?.format('YYYY-MM-DD'),
        date_to: range?.[1]?.format('YYYY-MM-DD'),
        ...(overdueOnly ? { overdue: true } : {}),
        page,
        page_size: pageSize,
      })
      setCases(res.data || [])
      setTotal(res.meta?.total || 0)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '加载离职办理列表失败')
    } finally {
      setLoading(false)
    }
  }, [status, department, keyword, range, overdueOnly, page, pageSize])

  const loadStats = useCallback(async () => {
    try {
      const res = await fetchOffboardingCaseStats()
      setStats(res.data)
    } catch {
      setStats(null) // 统计失败不影响列表
    }
  }, [])

  useEffect(() => {
    // 筛选 / 分页变化即拉列表。加载函数首行同步置 loading 是刻意的即时反馈，与仓库其它页面一致
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  useEffect(() => {
    fetchDepartmentsAction({ page_size: 200 })
      .then((r) => setDepartments((r.data || []).map((d: { name: string }) => ({ value: d.name, label: d.name }))))
      .catch(() => {})
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 同上：统计拉取后的写入在 await 之后
    void loadStats()
  }, [loadStats])

  // 输入框即时回显；防抖 300ms 后才写入查询条件（此前每敲一个字发一次请求）
  const { run: debouncedKeyword } = useDebouncedCallback((value: string) => {
    setPage(1)
    setKeyword(value.trim())
  }, 300)

  const pickStat = (next: { status?: OffboardingCaseStatus | ''; overdue?: boolean }) => {
    setStatus(next.status ?? '')
    setOverdueOnly(next.overdue ?? false)
    setPage(1)
  }

  const openDetail = (id: string) => {
    setDetailId(id)
    setDrawerOpen(true)
  }

  const columns: ColumnsType<OffboardingCase> = [
    { title: '申请编号', dataIndex: 'case_no', key: 'case_no', width: 150 },
    {
      title: '员工',
      dataIndex: 'name',
      key: 'name',
      width: 110,
      fixed: 'left',
      render: (value: string, row) => (
        <Space size={4}>
          <span>{value}</span>
          {row.health_check_required && !row.health_check_done && (
            <Tooltip title="重点岗位：离岗体检未登记，尚不能发起审批">
              <WarningOutlined className="text-[var(--color-warning)]" aria-label="待完成离岗体检" />
            </Tooltip>
          )}
        </Space>
      ),
    },
    { title: '工号', dataIndex: 'employee_number', key: 'employee_number', width: 110 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 150 },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 140,
      render: (value: string, row) => {
        const until = daysUntil(value)
        // 临期提示只对还在审批 / 清退里的单有意义：清退交接应于离职日前 2 天发起
        const inFlow = row.status === 'approving' || row.status === 'clearing' || row.status === 'draft'
        return (
          <div className="leading-[1.3]">
            <div>{value}</div>
            {inFlow && (
              <div className={`text-[12px] ${until.urgent ? 'text-[var(--color-error)] font-medium' : 'text-[var(--color-steel)]'}`}>
                {until.text}
              </div>
            )}
          </div>
        )
      },
    },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 100,
      render: (value: string) => <Tag color={DEPARTURE_TYPE_TAG_COLORS[value] || 'default'}>{value}</Tag>,
    },
    {
      title: '办理状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (value: string, row) => (
        <Tag color={OFFBOARDING_STATUS_TAG_COLORS[value] || 'default'}>{row.status_label}</Tag>
      ),
    },
    {
      title: '证明',
      key: 'cert',
      width: 96,
      render: (_value: unknown, row) =>
        row.cert_issued_at ? <Tag color="success">已开具</Tag> : <Tag>未开具</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_value: unknown, row) => (
        <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row.id) }}>
          办理
        </Button>
      ),
    },
  ]

  const counts = stats?.counts || {}
  const statItems: { title: string; value: number; key: string; active: boolean; danger?: boolean; onClick: () => void }[] = [
    {
      title: '进行中',
      value: stats?.active || 0,
      key: 'active',
      active: !status && !overdueOnly,
      onClick: () => pickStat({ status: '', overdue: false }),
    },
    { title: '待发起审批', value: counts.draft || 0, key: 'draft', active: status === 'draft' && !overdueOnly, onClick: () => pickStat({ status: 'draft' }) },
    { title: '离职审批中', value: counts.approving || 0, key: 'approving', active: status === 'approving' && !overdueOnly, onClick: () => pickStat({ status: 'approving' }) },
    { title: '清退会签中', value: counts.clearing || 0, key: 'clearing', active: status === 'clearing' && !overdueOnly, onClick: () => pickStat({ status: 'clearing' }) },
    { title: '待开具证明', value: counts.cert_issuing || 0, key: 'cert_issuing', active: status === 'cert_issuing' && !overdueOnly, onClick: () => pickStat({ status: 'cert_issuing' }) },
    { title: '证明送达中', value: counts.delivering || 0, key: 'delivering', active: status === 'delivering' && !overdueOnly, onClick: () => pickStat({ status: 'delivering' }) },
    { title: '待办结', value: counts.signed || 0, key: 'signed', active: status === 'signed' && !overdueOnly, onClick: () => pickStat({ status: 'signed' }) },
    {
      title: '临期 / 超期',
      value: stats?.overdue || 0,
      key: 'overdue',
      active: overdueOnly,
      danger: (stats?.overdue || 0) > 0,
      onClick: () => {
        setStatus('')
        setOverdueOnly(true)
        setPage(1)
      },
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="离职办理"
        description="从发起到办结的全流程：离职审批 → 清退会签 → 开具证明 → 送达签收 → 办结，每个环节办结后自动推进到下一步。"
      />

      <div className="flex flex-wrap gap-2">
        {statItems.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={item.onClick}
            aria-pressed={item.active}
            className={`rounded-[var(--rounded-lg)] border px-4 py-2 text-left transition-colors ${
              item.active
                ? 'border-[var(--color-ink)] bg-[var(--color-surface)]'
                : 'border-[var(--color-hairline)] bg-[var(--color-canvas)]'
            }`}
          >
            <Statistic
              title={<span className="text-[12px] text-[var(--color-slate)]">{item.title}</span>}
              value={item.value}
              valueStyle={{
                fontSize: 20,
                lineHeight: 1.3,
                fontWeight: 600,
                color: item.danger ? 'var(--color-error)' : 'var(--color-ink)',
              }}
            />
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            发起离职办理
          </Button>
        )}
        <Input
          placeholder="搜索姓名 / 工号 / 部门 / 岗位"
          value={keywordInput}
          onChange={(e) => {
            setKeywordInput(e.target.value)
            debouncedKeyword(e.target.value)
          }}
          prefix={<SearchOutlined />}
          // antd 输入框自带 width:100%，宽度须走 style
          style={{ width: 240 }}
          allowClear
        />
        <Select
          placeholder="办理状态"
          value={status || undefined}
          onChange={(value) => pickStat({ status: (value || '') as OffboardingCaseStatus | '' })}
          allowClear
          style={{ width: 150 }}
          options={STATUS_OPTIONS}
        />
        <Select
          placeholder="部门"
          value={department || undefined}
          showSearch
          optionFilterProp="label"
          onChange={(value) => { setDepartment(value || ''); setPage(1) }}
          allowClear
          style={{ width: 180 }}
          options={departments}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(value) => { setRange(value as Range); setPage(1) }}
          placeholder={['离职日期起', '离职日期止']}
        />
      </div>

      {loadError && <Alert type="error" showIcon title={loadError} />}
      {overdueOnly && (
        <Alert
          type="warning"
          showIcon
          closable
          onClose={() => pickStat({ status: '', overdue: false })}
          title="只看临期 / 超期：仍在离职审批或清退会签中，且距离离职日已不足 2 天（含已过）"
        />
      )}

      <Table<OffboardingCase>
        columns={columns}
        dataSource={cases}
        rowKey="id"
        loading={loading}
        onRow={(row) => ({ onClick: () => openDetail(row.id), style: { cursor: 'pointer' } })}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        scroll={{ x: 1150 }}
      />

      <OffboardingNewCaseModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false)
          void loadStats()
          openDetail(id)
        }}
      />
      <OffboardingCaseDrawer
        open={drawerOpen}
        caseId={detailId}
        onClose={() => setDrawerOpen(false)}
        onChanged={() => {
          void load()
          void loadStats()
        }}
      />
    </div>
  )
}
