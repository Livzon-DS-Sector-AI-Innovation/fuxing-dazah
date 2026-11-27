'use client'

// 离职办理：办结单列表 + 发起入口 + 办理抽屉。日常办事在这里——台账是结果数据，这里是过程。
// 页头环节卡可以直接点：点到哪个环节，列表就筛到哪个环节（临期同理）；
// 每行的「下一步」说明现在轮到谁做什么，不熟悉流程的人不用自己记顺序。

import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, DatePicker, Input, Select, Space, Table, Tag, Tooltip, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import {
  fetchDepartmentsAction,
  fetchOffboardingCaseStats,
  fetchOffboardingCases,
  queryDepartureLedger,
} from '@/actions/hr'
import { useDebouncedCallback, useHasPermission } from '@/hooks/hr'
import {
  DEPARTURE_TYPE_TAG_COLORS,
  NEXT_STEP_HINT,
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

interface StageCard {
  title: string
  value: number
  key: string
  active: boolean
  danger?: boolean
  /** 这张卡对应的环节里，轮到谁做什么 */
  hint: string
  onClick: () => void
}

export default function OffboardingBoardClient({
  initialCaseId = null,
  initialStage = null,
  onChanged,
  onGoLedger,
}: {
  /** 进页面就直接打开的办理单（从别的页面跳转过来时带） */
  initialCaseId?: string | null
  /** 进页面就筛在某个环节：办理状态，或 'overdue' = 临期 / 超期（人事看板待办栏用） */
  initialStage?: string | null
  /** 办理推进之后通知外层（台账要跟着刷新） */
  onChanged?: () => void
  /** 切到「离职台账」页签去挑人 */
  onGoLedger?: () => void
}) {
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
  const [status, setStatus] = useState<OffboardingCaseStatus | ''>(
    initialStage && initialStage !== 'overdue' ? (initialStage as OffboardingCaseStatus) : '',
  )
  const [overdueOnly, setOverdueOnly] = useState(initialStage === 'overdue')
  const [department, setDepartment] = useState('')
  const [range, setRange] = useState<Range>(null)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [stats, setStats] = useState<OffboardingCaseStats | null>(null)
  const [unstarted, setUnstarted] = useState<number | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  // 初值直接取跳转带来的单号：本页是默认页签、随外壳一起挂载，不需要再写 effect 去打开
  const [detailId, setDetailId] = useState<string | null>(initialCaseId)
  const [drawerOpen, setDrawerOpen] = useState(Boolean(initialCaseId))
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
    // 台账里还没发起办理的人数：给「从台账挑人发起」指路（拿不到就不显示）
    queryDepartureLedger({ approval_status: 'none', page: 1, page_size: 1 })
      .then((r) => setUnstarted(r.meta?.total ?? null))
      .catch(() => setUnstarted(null))
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

  // 列宽只给窄列定死，其余自适应：办理页是日常入口，不该在常见屏宽下出横向滚动条
  const columns: ColumnsType<OffboardingCase> = [
    { title: '申请编号', dataIndex: 'case_no', key: 'case_no' },
    {
      title: '员工',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => (
        <Space size={4}>
          <span>{value}</span>
          {row.health_check_required && !row.health_check_done && (
            <Tooltip title="重点岗位：离岗体检未登记，尚不能提交审批">
              <WarningOutlined className="text-[var(--color-warning)]" aria-label="待完成离岗体检" />
            </Tooltip>
          )}
        </Space>
      ),
    },
    { title: '工号', dataIndex: 'employee_number', key: 'employee_number', width: 110 },
    { title: '部门', dataIndex: 'department', key: 'department' },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 120,
      render: (value: string, row) => {
        const until = daysUntil(value)
        // 临期提示只对还没走出审批 / 清退的单有意义：清退交接应于离职日前 2 天发起
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
      title: '下一步',
      key: 'next',
      render: (_value: unknown, row) => (
        <span className={
          row.status === 'closed' || row.status === 'canceled'
            ? 'text-[var(--color-steel)]'
            : 'text-[var(--color-ink)]'
        }>
          {NEXT_STEP_HINT[row.status]}
        </span>
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
      render: (_value: unknown, row) => (
        <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row.id) }}>
          {row.status === 'closed' ? '查看' : '办理'}
        </Button>
      ),
    },
  ]

  const counts = stats?.counts || {}
  const stageCards: StageCard[] = [
    {
      title: '进行中',
      value: stats?.active || 0,
      key: 'active',
      active: !status && !overdueOnly,
      hint: '全部还没办结的',
      onClick: () => pickStat({ status: '', overdue: false }),
    },
    { title: '待提交审批', value: counts.draft || 0, key: 'draft', active: status === 'draft' && !overdueOnly, hint: 'HR：提交部门审批', onClick: () => pickStat({ status: 'draft' }) },
    { title: '部门审批中', value: counts.approving || 0, key: 'approving', active: status === 'approving' && !overdueOnly, hint: '负责人审批；通过后 HR 登记', onClick: () => pickStat({ status: 'approving' }) },
    { title: '清退会签中', value: counts.clearing || 0, key: 'clearing', active: status === 'clearing' && !overdueOnly, hint: '四部门清退；完成后 HR 登记', onClick: () => pickStat({ status: 'clearing' }) },
    { title: '待开具证明', value: counts.cert_issuing || 0, key: 'cert_issuing', active: status === 'cert_issuing' && !overdueOnly, hint: 'HR：核对并开具证明', onClick: () => pickStat({ status: 'cert_issuing' }) },
    { title: '证明送达中', value: counts.delivering || 0, key: 'delivering', active: status === 'delivering' && !overdueOnly, hint: 'HR：发给员工，等员工签字', onClick: () => pickStat({ status: 'delivering' }) },
    { title: '待办结', value: counts.signed || 0, key: 'signed', active: status === 'signed' && !overdueOnly, hint: '员工已签字；HR 办结', onClick: () => pickStat({ status: 'signed' }) },
    {
      title: '临期 / 超期',
      value: stats?.overdue || 0,
      key: 'overdue',
      active: overdueOnly,
      danger: (stats?.overdue || 0) > 0,
      hint: '距离职日不足 2 天还在审批 / 清退',
      onClick: () => pickStat({ status: '', overdue: true }),
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="离职办理"
        description="一个人一张办理单，从发起到办结：提交部门审批 → 部门审批 → 清退会签 → 开具证明 → 送达签收 → 员工签字 → 办结。"
      />

      <div className="flex flex-wrap gap-2">
        {stageCards.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={item.onClick}
            aria-pressed={item.active}
            title={item.hint}
            className={`rounded-[var(--rounded-lg)] border px-4 py-2 text-left transition-colors ${
              item.active
                ? 'border-[var(--color-ink)] bg-[var(--color-surface)]'
                : 'border-[var(--color-hairline)] bg-[var(--color-canvas)] hover:border-[var(--color-steel)]'
            }`}
          >
            <div className="text-[12px] text-[var(--color-slate)]">{item.title}</div>
            <div
              className="text-[20px] font-semibold leading-[1.3]"
              style={{ color: item.danger ? 'var(--color-error)' : 'var(--color-ink)' }}
            >
              {item.value}
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            发起离职办理
          </Button>
        )}
        {canManage && onGoLedger && unstarted !== null && (
          <Button onClick={onGoLedger}>
            从离职台账挑人{unstarted > 0 ? `（${unstarted} 人还没发起）` : ''}
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
          title="只看临期 / 超期：仍在部门审批或清退会签中，且距离职日已不足 2 天（含已过）"
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
        locale={{
          emptyText: (
            <div className="space-y-3 py-6 text-center">
              <Typography.Text className="text-[var(--color-slate)]">
                {status || overdueOnly
                  ? '这个环节下暂时没有办理单。'
                  : '还没有离职办理单。要给某位员工办离职，从离职台账里找到这个人的那一行，点「发起办理」就能带出离职日期和类型。'}
              </Typography.Text>
              <div className="flex flex-wrap justify-center gap-2">
                {!status && !overdueOnly && canManage && (
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                    按姓名 / 工号发起
                  </Button>
                )}
                {onGoLedger && (
                  <Button onClick={onGoLedger}>
                    去离职台账挑人{unstarted && unstarted > 0 ? `（${unstarted} 人还没发起）` : ''}
                  </Button>
                )}
              </div>
            </div>
          ),
        }}
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
          onChanged?.()
        }}
      />
    </div>
  )
}
