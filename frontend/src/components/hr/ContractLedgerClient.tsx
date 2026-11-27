'use client'

// 劳动合同台账（在职）：默认「需要处理」视图 + 环节卡片 + 行内「下一步」动作。
// 期限/状态标签由后端按签订次数自动计算下发，前端只读展示；
// 点环节卡看某个环节，行上的按钮直接进到那份合同的办理抽屉（动作都在抽屉里做，单入口防误触）。

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Button, Checkbox, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { FileAddOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import PageHeader from '@/components/hr/PageHeader'
import ContractDetailDrawer from '@/components/hr/ContractDetailDrawer'
import ContractFormModal from '@/components/hr/ContractFormModal'
import { LedgerImportModal } from '@/components/hr'
import { fetchDepartmentsAction, fetchLaborContracts, fetchLaborContractStats } from '@/actions/hr'
import { useHasPermission } from '@/hooks/hr'
import { CONTRACT_TODO_CARDS, rowNextAction } from '@/lib/hr'
import type { LaborContract, LaborContractStatus, LaborContractStats, ContractTodoKey } from '@/types/hr'

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'active', label: '生效中' },
  { value: 'pending_renewal,renewing', label: '公告期/续签办理中' },
  { value: 'expired_unrenewed', label: '到期未续签' },
  { value: 'terminated', label: '已终止' },
  { value: 'superseded', label: '已续签取代' },
]

const STATUS_TAG_COLORS: Record<LaborContractStatus, string> = {
  active: 'green',
  pending_renewal: 'orange',
  renewing: 'blue',
  superseded: 'default',
  terminated: 'red',
  expired_unrenewed: 'volcano',
}

/** 行上操作按钮的短文案（「下一步」列已经写了完整说法） */
const ROW_ACTION_SHORT: Record<string, string> = {
  decide: '去登记',
  renew: '办理续签',
  stamp: '去盖章',
  deliver: '去领取',
  sign: '查看',
  archive: '去归档',
  transfer: '转离职',
}

function daysUntil(endDate?: string | null): number | null {
  if (!endDate) return null
  const diff = new Date(endDate).getTime() - Date.now()
  return Math.ceil(diff / 86400000)
}

function endDateText(row: LaborContract): string {
  if (!row.end_date) return '无固定期限'
  const days = daysUntil(row.end_date)
  if (row.status === 'active' && days !== null && days >= 0 && days <= 50) {
    return `${row.end_date}（${days} 天后到期）`
  }
  return row.end_date
}

/** 环节卡片取值：attention 不在 stats 里单独占键，取 attention_total */
const cardCount = (stats: LaborContractStats | null, key: ContractTodoKey) =>
  key === 'attention' ? stats?.attention_total ?? 0 : stats?.[key] ?? 0

interface Props {
  /** 外层通知刷新（在电子档案库归档后切回来，「归档」列要是最新的） */
  refreshKey?: number
  /** 进页面就筛在某个「待我处理」口径（?todo=，人事看板待办栏用）；不传默认看「需要处理」 */
  initialTodo?: ContractTodoKey
  /** 台账里推进了流程之后通知外层 */
  onChanged?: () => void
}

export default function ContractLedgerClient({ refreshKey = 0, initialTodo, onChanged }: Props) {
  const { message } = App.useApp()
  // 水合安全的权限判断：页面在 Suspense 边界内
  const canManage = useHasPermission('hr:contract:manage')
  const canApprove = useHasPermission('hr:contract:approve')

  const [rows, setRows] = useState<LaborContract[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<LaborContractStats | null>(null)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  // 默认只看「需要处理」：不来回翻历史合同
  const [todo, setTodo] = useState<ContractTodoKey | undefined>(initialTodo ?? 'attention')
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [expiringDays, setExpiringDays] = useState<number | undefined>()
  const [department, setDepartment] = useState<string | undefined>()
  const [includeHistory, setIncludeHistory] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const seqRef = useRef(0)

  const listParams = useCallback(
    (targetPage: number) => ({
      todo,
      status,
      keyword: keyword || undefined,
      expiring_days: expiringDays,
      department: department || undefined,
      include_history: includeHistory,
      page: targetPage,
      page_size: pageSize,
    }),
    [todo, status, keyword, expiringDays, department, includeHistory, pageSize],
  )

  // 事件驱动的刷新（翻页 / 刷新按钮 / 录入后）：可以直接进 loading。
  // 每页条数可能和 state 里的不一样（刚改还没生效），由调用方显式传
  const load = useCallback(
    async (targetPage = page, targetPageSize = pageSize) => {
      // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
      const seq = ++seqRef.current
      setLoading(true)
      try {
        const r = await fetchLaborContracts({ ...listParams(targetPage), page_size: targetPageSize })
        if (seq !== seqRef.current) return // 过期响应丢弃
        setRows(r.data)
        setTotal(r.meta.total)
      } catch (e) {
        if (seq === seqRef.current) message.error(e instanceof Error ? e.message : '加载台账失败')
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    },
    [message, page, pageSize, listParams],
  )

  const loadStats = useCallback(async () => {
    try {
      setStats((await fetchLaborContractStats(department || undefined)).data)
    } catch {
      setStats(null) // 统计失败不影响列表
    }
  }, [department])

  // 筛选变化重新拉取第一页：setState 全部在 await 之后，不在 effect 里同步触发级联渲染
  // （回到第一页由筛选控件的 onChange 负责，也就没有「setState 后立刻读旧闭包」的问题）
  useEffect(() => {
    const seq = ++seqRef.current
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchLaborContracts(listParams(1))
        if (cancelled || seq !== seqRef.current) return
        setRows(r.data)
        setTotal(r.meta.total)
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载台账失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listParams])

  useEffect(() => {
    // 统计拉取后的写状态在 await 之后，不在 effect 里同步触发级联渲染
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStats()
    fetchDepartmentsAction({ page_size: 200 })
      .then((r) => setDepartments((r.data || []).map((d: { name: string }) => ({ value: d.name, label: d.name }))))
      .catch(() => {})
    return () => { seqRef.current += 1 }
    // message 刻意不进依赖；loadStats 随部门筛选变化由下面的 effect 负责
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 部门筛选变化 / 外层通知刷新（电子档案库归档后）：重拉统计与当前页
  const firstRefreshKey = useRef(refreshKey)
  const firstDepartment = useRef(department)
  useEffect(() => {
    if (refreshKey === firstRefreshKey.current && department === firstDepartment.current) return
    firstRefreshKey.current = refreshKey
    firstDepartment.current = department
    void loadStats()
    void load()
  }, [refreshKey, department, loadStats, load])

  /** 选环节卡：清掉状态 / 到期窗口筛选（两者是并列的两种看法） */
  const pickTodo = (key: ContractTodoKey | undefined) => {
    setTodo(key)
    setStatus(undefined)
    setExpiringDays(undefined)
    setPage(1)
  }

  const pickStatus = (value: string | undefined) => {
    setStatus(value)
    setTodo(undefined)
    setPage(1)
  }

  const cards: { key: ContractTodoKey | undefined; title: string; value: number; hint: string; active: boolean }[] = [
    {
      key: 'attention',
      title: '需要处理',
      value: stats?.attention_total ?? 0,
      hint: '六个环节里轮到你办的合同都在这里',
      active: todo === 'attention',
    },
    ...CONTRACT_TODO_CARDS.map((card) => ({
      key: card.key as ContractTodoKey | undefined,
      title: card.title,
      value: cardCount(stats, card.key),
      hint: card.hint,
      active: todo === card.key,
    })),    {
      key: undefined,
      title: '全部合同',
      value: -1,
      hint: '在职人员的有效合同（不含已终止、已续签取代）',
      active: todo === undefined && !status && !expiringDays,
    },
  ]

  // 列宽合计约 1180：1440 宽度下不横向滚动即可看全；「下一步」列自适应
  const columns: ColumnsType<LaborContract> = [
    {
      title: '姓名 / 工号',
      width: 128,
      render: (_, r) => (
        <div>
          <div className="font-medium">{r.name}</div>
          <div className="text-xs text-gray-500">{r.employee_number}</div>
        </div>
      ),
    },
    { title: '部门', dataIndex: 'department', width: 116, ellipsis: { showTitle: true } },
    { title: '岗位', dataIndex: 'position', width: 96, render: (v) => v || '-', ellipsis: { showTitle: true } },
    { title: '签订次序', dataIndex: 'seq_label', width: 104, ellipsis: { showTitle: true } },
    { title: '期限', dataIndex: 'term_label', width: 72 },
    {
      title: '起始 ~ 到期',
      width: 184,
      render: (_, r) => (
        <span className="text-[13px]">
          {r.start_date || '-'} ~ {endDateText(r)}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 92,
      render: (_, r) => (
        <Tooltip title={r.terminated_reason || r.remark || undefined}>
          <Tag color={STATUS_TAG_COLORS[r.status] ?? 'default'}>{r.status_label}</Tag>
        </Tooltip>
      ),
    },
    { title: '学历', dataIndex: 'education', width: 64, render: (v) => v || '-' },
    {
      title: '下一步',
      key: 'next',
      render: (_, r) => {
        const action = rowNextAction(r)
        if (!action) {
          return <span className="text-xs text-gray-400">{r.status === 'terminated' ? '已终止' : r.status === 'superseded' ? '已续签取代' : '正常履约中'}</span>
        }
        return (
          <Tooltip title={action.hint}>
            <span className="text-[13px] text-[var(--color-ink)]">{action.label}</span>
          </Tooltip>
        )
      },
    },
    {
      title: '归档',
      width: 72,
      render: (_, r) => (
        <Tag color={r.archive_status === 'archived' ? 'green' : 'orange'}>
          {r.archive_status === 'archived' ? '已归档' : '未归档'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 92,
      render: (_, r) => {
        const action = rowNextAction(r)
        if (!action) return <Button size="small" onClick={() => setDetailId(r.id)}>详情</Button>
        return (
          <Button type="link" size="small" onClick={() => setDetailId(r.id)}>
            {ROW_ACTION_SHORT[action.kind]}
          </Button>
        )
      },
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="劳动合同台账"
        description="合同签订、到期预警、续签审批、盖章领取与归档全流程台账（期限按签订次数自动计算）。默认只看需要处理的合同。"
        actions={
          canManage && (
            <Space>
              <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
                Excel导入
              </Button>
              <Button type="primary" icon={<FileAddOutlined />} onClick={() => setFormOpen(true)}>
                录入合同
              </Button>
            </Space>
          )
        }
      />

      <div className="flex flex-wrap gap-2">
        {cards.map((card) => (
          <button
            key={card.key ?? '__all'}
            type="button"
            onClick={() => pickTodo(card.key)}
            aria-pressed={card.active}
            title={card.hint}
            className={`rounded-[var(--rounded-lg)] border px-4 py-2 text-left transition-colors ${
              card.active
                ? 'border-[var(--color-ink)] bg-[var(--color-surface)]'
                : 'border-[var(--color-hairline)] bg-[var(--color-canvas)] hover:border-[var(--color-steel)]'
            }`}
          >
            <div className="text-[12px] text-[var(--color-slate)]">{card.title}</div>
            <div className="text-[20px] font-semibold leading-[1.3] text-[var(--color-ink)]">
              {card.value < 0 ? '—' : card.value}
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Select
          allowClear
          placeholder="按状态看"
          style={{ width: 180 }}
          value={status}
          onChange={(v) => pickStatus(v)}
          options={STATUS_FILTERS}
        />
        <Select
          allowClear
          placeholder="到期窗口"
          style={{ width: 170 }}
          value={expiringDays}
          onChange={(v) => { setExpiringDays(v); setTodo(undefined); setPage(1) }}
          options={[
            { value: 50, label: '公告期（50 天内到期）' },
            { value: 90, label: '90 天内到期' },
            { value: 180, label: '半年内到期' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="部门"
          style={{ width: 170 }}
          value={department}
          onChange={(v) => { setDepartment(v); setPage(1) }}
          options={departments}
        />
        <Input.Search
          allowClear
          placeholder="姓名 / 工号"
          style={{ width: 180 }}
          onSearch={(v) => {
            // 只更新筛选状态：拉取由上面的 effect 负责
            setKeyword(v.trim())
            setPage(1)
          }}
        />
        <Tooltip title="刷新">
          <Button aria-label="刷新" icon={<ReloadOutlined />} onClick={() => { void load(); void loadStats() }} />
        </Tooltip>
        <Checkbox
          checked={includeHistory}
          onChange={(e) => { setIncludeHistory(e.target.checked); setPage(1) }}
        >
          显示已终止 / 已续签取代的历史合同
        </Checkbox>
      </div>

      {!canManage && !canApprove && (
        <Typography.Text className="text-[13px] text-[var(--color-slate)]">
          您只有查看权限；登记部门意见、续签、盖章、领取等操作需要相应权限。
        </Typography.Text>
      )}

      <Table<LaborContract>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1180 }}
        locale={{
          emptyText: (
            <div className="py-6 text-center text-[var(--color-slate)]">
              {todo === 'attention'
                ? '目前没有需要处理的合同：各部门意见已登记、续签都已盖章、领取并归档。'
                : status || expiringDays || todo
                  ? '这个筛选下没有合同。'
                  : '没有符合条件的合同。可以用「Excel导入」或「录入合同」把纸质台账录进来。'}
            </div>
          ),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 份合同`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
            void load(p, ps)
          },
        }}
      />

      <ContractDetailDrawer
        contractId={detailId}
        canManage={canManage}
        canApprove={canApprove}
        onClose={() => setDetailId(null)}
        onChanged={() => {
          void load()
          void loadStats()
          onChanged?.()
        }}
      />

      <LedgerImportModal
        open={importOpen}
        ledger="contract"
        label="劳动合同"
        onClose={() => setImportOpen(false)}
        onSuccess={() => {
          setImportOpen(false)
          void load(1)
          void loadStats()
        }}
      />

      <ContractFormModal
        open={formOpen}
        mode="create"
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false)
          setPage(1)
          void load(1)
          void loadStats()
        }}
      />
    </div>
  )
}
