'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { App, Button, Input, Popconfirm, Popover, Select, Skeleton, Spin, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined, SearchOutlined, TeamOutlined, WarningOutlined,
} from '@ant-design/icons'

import {
  deletePositionByName, fetchDepartmentsAction, fetchPositions,
} from '@/actions/hr'
import { useHasPermission } from '@/hooks/hr'
import type { PositionOption } from '@/types/hr'
import PageHeader from '@/components/hr/PageHeader'
import PositionFormModal, { type CreatedPosition } from './PositionFormModal'
import styles from './positions.module.css'

/** 移动端部门下拉里「全部岗位」对应的值（真实部门名不会用到这个前缀） */
const ALL = '__all__'
/** 关联培训大类一格里最多直接显示几个，其余折叠成「+N」 */
const CHIP_LIMIT = 3

/** 表格行：「全部岗位」视图里同一部门的行排在一起，首行记下跨行数来合并部门单元格。
 *  categories 在公共类型里可选，这里加载时已补成空数组 */
type PositionRow = Omit<PositionOption, 'categories'> & {
  categories: string[]
  groupFirst?: boolean
  groupSpan?: number
  groupLast?: boolean
}

interface NavItem {
  /** null 表示「全部岗位」 */
  name: string | null
  label: string
  count: number
}

const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback)
const byName = (a: string, b: string) => a.localeCompare(b, 'zh-CN')
const normalize = (list: PositionOption[]): PositionOption[] =>
  list.map((p) => ({ ...p, categories: p.categories ?? [] }))

/** 关联培训大类：次要信息，折叠显示是为了让行高保持整齐 */
function CategoryChips({ categories }: { categories: string[] }) {
  if (!categories.length) return <span className="text-[var(--color-stone)]">—</span>
  const rest = categories.length - CHIP_LIMIT
  return (
    <span className="flex flex-wrap items-center gap-1">
      {categories.slice(0, CHIP_LIMIT).map((c) => (
        <span key={c} className={styles.chip}>{c}</span>
      ))}
      {rest > 0 && (
        <Popover
          title="关联培训大类"
          placement="topLeft"
          content={(
            <span className="flex max-w-xs flex-wrap gap-1">
              {categories.map((c) => <span key={c} className={styles.chip}>{c}</span>)}
            </span>
          )}
        >
          <span className={`${styles.chip} ${styles.chipMore} cursor-default`}>+{rest}</span>
        </Popover>
      )}
    </span>
  )
}

function EmptyState({ icon, title, description, action }: {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-[var(--color-tint-lavender)]">
        {icon}
      </span>
      <p className="text-[14px] font-medium text-[var(--color-charcoal)]">{title}</p>
      {description && (
        <p className="max-w-sm text-[13px] leading-relaxed text-[var(--color-steel)]">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** 左栏的一项：部门名 + 岗位数。没设岗位的部门整行置灰，当前项用主色淡底 */
function NavButton({ item, active, onClick }: { item: NavItem; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-current={active ? 'true' : undefined}
      onClick={onClick}
      className={`flex h-9 w-full cursor-pointer items-center gap-2 rounded-[var(--rounded-md)] px-3 text-left text-[14px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-primary)] ${
        active
          ? 'bg-[var(--color-primary-bg)] font-medium text-[var(--color-ink)]'
          : item.count === 0
            ? 'text-[var(--color-steel)] hover:bg-[var(--color-hairline-soft)] hover:text-[var(--color-charcoal)]'
            : 'text-[var(--color-charcoal)] hover:bg-[var(--color-hairline-soft)]'
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      <span
        className={`text-[12px] tabular-nums ${
          active ? 'text-[var(--color-primary)]' : 'text-[var(--color-stone)]'
        }`}
      >
        {item.count}
      </span>
    </button>
  )
}

export default function PositionManager() {
  const { message } = App.useApp()
  const canManage = useHasPermission('hr:position:manage')

  const [positions, setPositions] = useState<PositionOption[]>([])
  const [departments, setDepartments] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [retryTick, setRetryTick] = useState(0)
  const [activeDept, setActiveDept] = useState<string | null>(null)
  const [deptKeyword, setDeptKeyword] = useState('')
  const [keyword, setKeyword] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)

  const loadSeq = useRef(0)
  const highlightTimer = useRef<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  /** 首屏要的两份数据一起等：部门顺序决定导航和分组的排列，只到一半会先乱序再重排。
   *  部门列表拉不到不阻断——导航退化为只列有岗位的部门 */
  const fetchInitial = useCallback(async () => {
    const [posRes, deptRes] = await Promise.allSettled([
      fetchPositions(),
      fetchDepartmentsAction({ page_size: 200 }),
    ])
    if (posRes.status === 'rejected') throw posRes.reason
    return {
      positions: normalize(posRes.value),
      departments: deptRes.status === 'fulfilled' ? (deptRes.value.data ?? []).map((d) => d.name) : [],
    }
  }, [])

  // 请求写在 effect 内部，setState 都在 await 之后
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetchInitial()
        if (!cancelled) {
          setPositions(res.positions)
          setDepartments(res.departments)
          setLoadFailed(false)
        }
      } catch {
        if (!cancelled) setLoadFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // retryTick：点「重试」时加一，重新走一遍
  }, [fetchInitial, retryTick])

  // 增删改之后的刷新。序号守卫：慢响应回来时若已有更新的请求，丢弃这份旧数据
  const refresh = useCallback(async () => {
    const seq = ++loadSeq.current
    try {
      const list = await fetchPositions()
      if (seq === loadSeq.current) setPositions(normalize(list))
    } catch {
      message.error('岗位列表刷新失败，请刷新页面')
    }
  }, [message])

  // 导航与新增弹窗的部门下拉共用这个顺序：组织架构在前，只出现在岗位表里的历史部门名排在后面
  const orderedDepts = useMemo(() => {
    const known = new Set(departments)
    const extra = [...new Set(positions.map((p) => p.department))]
      .filter((name) => !known.has(name))
      .sort(byName)
    return [...departments, ...extra]
  }, [departments, positions])

  const navItems = useMemo<NavItem[]>(() => {
    const counts = new Map<string, number>()
    positions.forEach((p) => counts.set(p.department, (counts.get(p.department) ?? 0) + 1))
    const items = orderedDepts.map((name) => ({ name, label: name, count: counts.get(name) ?? 0 }))
    const kw = deptKeyword.trim().toLowerCase()
    return [
      { name: null, label: '全部岗位', count: positions.length },
      ...(kw ? items.filter((item) => item.label.toLowerCase().includes(kw)) : items),
    ]
  }, [orderedDepts, deptKeyword, positions])

  const rows = useMemo<PositionRow[]>(() => {
    const kw = keyword.trim().toLowerCase()
    const rank = (dept: string) => {
      const index = orderedDepts.indexOf(dept)
      return index === -1 ? Number.MAX_SAFE_INTEGER : index
    }
    const list: PositionRow[] = positions
      .filter((p) => (!activeDept || p.department === activeDept) && (!kw || p.name.toLowerCase().includes(kw)))
      .sort((a, b) => rank(a.department) - rank(b.department) || byName(a.name, b.name))
      .map((p) => ({ ...p, categories: p.categories ?? [] }))
    if (activeDept) return list
    for (let first = 0; first < list.length; ) {
      let last = first
      while (last + 1 < list.length && list[last + 1].department === list[first].department) last += 1
      list[first].groupFirst = true
      list[first].groupSpan = last - first + 1
      list[last].groupLast = true
      first = last + 1
    }
    return list
  }, [activeDept, keyword, orderedDepts, positions])

  const deptCount = useMemo(() => new Set(positions.map((p) => p.department)).size, [positions])
  const searching = keyword.trim() !== ''
  // 首屏数据没回来之前没有可报的数，先不显示，免得闪一下「0 个岗位」
  const summary = loading && positions.length === 0
    ? ''
    : searching
      ? `找到 ${rows.length} 个岗位`
      : activeDept
        ? `${rows.length} 个岗位`
        : `${positions.length} 个岗位，分布在 ${deptCount} 个部门`

  const selectDept = (name: string | null) => {
    setActiveDept(name)
    setKeyword('')
  }

  const handleDelete = async (row: PositionRow) => {
    setDeletingId(row.id)
    try {
      await deletePositionByName(row.name, row.department)
      message.success(`已删除岗位「${row.name}」`)
      await refresh()
    } catch (err) {
      message.error(errText(err, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  const handleCreated = (created: CreatedPosition) => {
    // 切到新岗位所在的部门并高亮那一行，让它出现在眼前
    setActiveDept(created.department)
    setKeyword('')
    setHighlightId(created.id)
    void refresh()
    if (highlightTimer.current) window.clearTimeout(highlightTimer.current)
    highlightTimer.current = window.setTimeout(() => setHighlightId(null), 2600)
  }

  // 新增的行可能排在视野之外：数据到位后把它滚进来
  useEffect(() => {
    if (!highlightId) return
    scrollRef.current?.querySelector(`[data-row-key="${highlightId}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [highlightId, positions])

  useEffect(() => () => {
    if (highlightTimer.current) window.clearTimeout(highlightTimer.current)
  }, [])

  // 编制人数不归这个页面维护（接口里的 headcount 只带不显示），所以只有名称、培训大类和操作
  const columns: ColumnsType<PositionRow> = []
  if (!activeDept) {
    columns.push({
      title: '部门',
      dataIndex: 'department',
      width: 180,
      onCell: (row) => (row.groupFirst
        ? { rowSpan: row.groupSpan, className: styles.groupCell }
        : { rowSpan: 0 }),
    })
  }
  columns.push(
    {
      title: '岗位名称',
      dataIndex: 'name',
      render: (name: string) => <span className="font-medium text-[var(--color-ink)]">{name}</span>,
    },
    {
      title: '关联培训大类',
      dataIndex: 'categories',
      render: (categories: string[]) => <CategoryChips categories={categories} />,
    },
  )
  if (canManage) {
    columns.push({
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, row) => (
        <Popconfirm
          title={`删除岗位「${row.name}」？`}
          // 后端会连带清掉该岗位的培训内容和 SOP 目录条目，员工档案不动
          description={row.categories.length
            ? `该岗位关联的 ${row.categories.length} 个培训大类和 SOP 目录条目会一并删除，不影响员工档案。`
            : '该岗位关联的 SOP 目录条目会一并删除，不影响员工档案。'}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => { void handleDelete(row) }}
        >
          <Button type="text" size="small" danger loading={deletingId === row.id}>删除</Button>
        </Popconfirm>
      ),
    })
  }

  const kw = keyword.trim()
  let emptyText: ReactNode
  if (loadFailed) {
    emptyText = (
      <EmptyState
        icon={<WarningOutlined className="text-xl text-[var(--color-warning)]" />}
        title="岗位列表加载失败"
        description="请稍后重试"
        action={(
          <Button onClick={() => { setLoading(true); setLoadFailed(false); setRetryTick((n) => n + 1) }}>
            重试
          </Button>
        )}
      />
    )
  } else if (kw) {
    emptyText = (
      <EmptyState
        icon={<SearchOutlined className="text-xl text-[var(--color-brand-purple)]" />}
        title={`没有找到与「${kw}」匹配的岗位`}
        action={<Button onClick={() => setKeyword('')}>清除搜索</Button>}
      />
    )
  } else if (activeDept) {
    emptyText = (
      <EmptyState
        icon={<TeamOutlined className="text-xl text-[var(--color-brand-purple)]" />}
        title={`「${activeDept}」还没有设置岗位`}
        description="设置后，这个部门的员工在档案、招聘和培训里才能选到对应岗位"
        action={canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>新增岗位</Button>
        ) : undefined}
      />
    )
  } else {
    emptyText = (
      <EmptyState
        icon={<TeamOutlined className="text-xl text-[var(--color-brand-purple)]" />}
        title="还没有设置岗位"
        description="按部门设置岗位后，员工档案、招聘和培训里才能选到"
        action={canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>新增岗位</Button>
        ) : undefined}
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 xl:h-full">
      <PageHeader
        title="岗位管理"
        description="维护各部门的岗位；员工档案、招聘、SOP 目录和培训里选的岗位都来自这里"
        actions={canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
            新增岗位
          </Button>
        ) : undefined}
      />

      <div className="grid grid-cols-1 overflow-hidden rounded-[var(--rounded-lg)] border border-[var(--color-hairline)] bg-[var(--color-canvas)] xl:min-h-0 xl:flex-1 xl:grid-cols-[240px_minmax(0,1fr)] xl:grid-rows-[minmax(0,1fr)]">
        {/* 左栏：部门导航。窄屏不显示，改用右栏顶部的部门下拉 */}
        <aside className="hidden min-h-0 flex-col border-[var(--color-hairline)] bg-[var(--color-surface-soft)] xl:flex xl:border-r">
          <div className="shrink-0 px-3 pt-3 pb-2">
            <Input
              allowClear
              aria-label="搜索部门"
              prefix={<SearchOutlined />}
              placeholder="搜索部门"
              value={deptKeyword}
              onChange={(e) => setDeptKeyword(e.target.value)}
            />
          </div>
          <nav aria-label="部门" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {/* 首屏两个请求回来之前列表还是空的：给骨架屏，别只留一个「全部岗位 0」 */}
            {loading && positions.length === 0 ? (
              <div className="pl-2 pr-10 pt-1">
                <Skeleton active title={false} paragraph={{ rows: 10 }} />
              </div>
            ) : (
              <ul className="flex flex-col gap-0.5">
                {navItems.map((item, index) => (
                  <li key={item.name ?? ALL}>
                    {/* 「全部岗位」和具体部门之间隔一条线 */}
                    {index === 1 && <div aria-hidden className="my-2 border-t border-[var(--color-hairline)]" />}
                    <NavButton
                      item={item}
                      active={activeDept === item.name}
                      onClick={() => selectDept(item.name)}
                    />
                  </li>
                ))}
                {navItems.length === 1 && (
                  <li className="px-3 py-6 text-center text-[13px] text-[var(--color-stone)]">没有匹配的部门</li>
                )}
              </ul>
            )}
          </nav>
        </aside>

        {/* 右栏：所选范围内的岗位 */}
        <section className="flex min-h-0 min-w-0 flex-col">
          <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[var(--color-hairline)] px-4 py-3">
            {/* 包一层再隐藏：antd 给 Select 根节点写死了 display，直接挂在它身上盖不过 */}
            <div className="xl:hidden">
              <Select
                style={{ width: 180 }}
                aria-label="选择部门"
                showSearch
                optionFilterProp="label"
                popupMatchSelectWidth={false}
                value={activeDept ?? ALL}
                onChange={(value: string) => selectDept(value === ALL ? null : value)}
                options={navItems.map((item) => ({
                  value: item.name ?? ALL,
                  label: `${item.label}（${item.count}）`,
                }))}
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <h2 className="truncate text-[16px] font-semibold leading-tight text-[var(--color-ink)]">
                {activeDept ?? '全部岗位'}
              </h2>
              <span className="text-[13px] text-[var(--color-steel)]">{summary}</span>
            </div>
            <Input
              allowClear
              aria-label="搜索岗位"
              prefix={<SearchOutlined />}
              placeholder="搜索岗位"
              style={{ width: 'min(220px, 100%)' }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </header>

          {/* 加载中和各种空状态都占满整块区域并居中；有行的时候才渲染表格 */}
          <div ref={scrollRef} className={styles.scrollBody}>
            {rows.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                {loading ? <Spin /> : emptyText}
              </div>
            ) : (
              <Table<PositionRow>
                className={styles.table}
                rowKey="id"
                size="middle"
                columns={columns}
                dataSource={rows}
                pagination={false}
                rowClassName={(row) => (row.id === highlightId ? styles.rowNew : '')}
              />
            )}
          </div>
        </section>
      </div>

      <PositionFormModal
        open={formOpen}
        defaultDepartment={activeDept ?? undefined}
        departments={orderedDepts}
        positions={positions}
        onClose={() => setFormOpen(false)}
        onCreated={handleCreated}
      />
    </div>
  )
}
