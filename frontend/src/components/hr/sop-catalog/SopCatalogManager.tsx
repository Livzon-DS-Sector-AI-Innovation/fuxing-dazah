'use client'

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { App, Button, Input, Select, Skeleton, Spin, Tooltip, Upload } from 'antd'
import {
  FolderOpenOutlined, PlusOutlined, SearchOutlined, UploadOutlined, WarningOutlined,
} from '@ant-design/icons'

import {
  deleteSopItem, fetchAllSopCatalog, fetchPositions, fetchTrainingDepartmentOptions, uploadSopCatalog,
} from '@/actions/hr'
import { useHasPermission } from '@/hooks/hr'
import type { PositionOption, SopCatalogItem } from '@/types/hr'
import PageHeader from '@/components/hr/PageHeader'
import SopGroupList from './SopGroupList'
import SopItemFormModal, { type CreatedSopItem } from './SopItemFormModal'
import SopSearchTable from './SopSearchTable'
import {
  buildSections, byName, errText, groupKey, itemMatches, sortForSearch, type SopGroup,
} from './sopGroups'
import styles from './sop-catalog.module.css'

/** 窄屏部门下拉里「全部部门」对应的值（真实部门名不会用到这个前缀） */
const ALL = '__all__'

interface NavItem {
  /** null 表示「全部部门」 */
  name: string | null
  label: string
  count: number
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
      {action && <div className="mt-2 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  )
}

/** 左栏的一项：部门名 + 条数。没有条目的部门整行置灰，当前项用主色淡底 */
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

export default function SopCatalogManager() {
  const { message, modal } = App.useApp()
  const canManage = useHasPermission('hr:training:manage')

  const [items, setItems] = useState<SopCatalogItem[]>([])
  const [positions, setPositions] = useState<PositionOption[]>([])
  const [departments, setDepartments] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [retryTick, setRetryTick] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [activeDept, setActiveDept] = useState<string | null>(null)
  const [deptKeyword, setDeptKeyword] = useState('')
  const [keyword, setKeyword] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [deletingIds, setDeletingIds] = useState<string[]>([])
  const [clearingKey, setClearingKey] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [highlightItemId, setHighlightItemId] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const highlightTimer = useRef<number | null>(null)

  // 首屏三份数据一起等。目录拉不到才算失败；部门、岗位两份选项拉不到不阻断——
  // 导航退化为只列目录里出现过的部门，新增弹窗里选不到组织架构岗位
  // 请求写在 effect 内部，setState 都在 await 之后
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const [catalogRes, deptRes, posRes] = await Promise.allSettled([
        fetchAllSopCatalog(),
        fetchTrainingDepartmentOptions(),
        fetchPositions(),
      ])
      if (cancelled) return
      if (catalogRes.status === 'rejected') {
        setLoadFailed(true)
        setLoading(false)
        return
      }
      const list = catalogRes.value.data
      setItems(list)
      if (deptRes.status === 'fulfilled') {
        setDepartments(deptRes.value.data)
      } else {
        const known = new Set<string>()
        for (const item of list) if (item.department) known.add(item.department)
        setDepartments([...known].sort(byName))
      }
      setPositions(posRes.status === 'fulfilled' ? posRes.value : [])
      setLoadFailed(false)
      setLoading(false)
    })()
    return () => { cancelled = true }
    // retryTick：点「重试」时加一，重新走一遍
  }, [retryTick])

  // 导航与新增弹窗的部门下拉共用这个顺序：接口给的顺序在前，只出现在目录里的部门名排在后面
  const orderedDepts = useMemo(() => {
    const known = new Set(departments)
    const extra = [...new Set(items.map((item) => item.department).filter((d): d is string => !!d))]
      .filter((name) => !known.has(name))
      .sort(byName)
    return [...departments, ...extra]
  }, [departments, items])

  const deptCounts = useMemo(() => {
    const counts = new Map<string, number>()
    items.forEach((item) => {
      if (item.department) counts.set(item.department, (counts.get(item.department) ?? 0) + 1)
    })
    return counts
  }, [items])

  const navItems = useMemo<NavItem[]>(() => {
    const navKw = deptKeyword.trim().toLowerCase()
    const list = orderedDepts.map((name) => ({ name, label: name, count: deptCounts.get(name) ?? 0 }))
    return [
      { name: null, label: '全部部门', count: items.length },
      ...(navKw ? list.filter((item) => item.label.toLowerCase().includes(navKw)) : list),
    ]
  }, [orderedDepts, deptCounts, deptKeyword, items.length])

  const kw = keyword.trim().toLowerCase()
  const searching = kw !== ''

  // 目录全量在本地：切部门、搜索都是纯前端筛选
  const scoped = useMemo(
    () => (activeDept ? items.filter((item) => item.department === activeDept) : items),
    [items, activeDept],
  )
  const matched = useMemo(() => {
    if (!searching) return scoped
    return sortForSearch(scoped.filter((item) => itemMatches(item, kw)), orderedDepts)
  }, [scoped, searching, kw, orderedDepts])
  const sections = useMemo(() => buildSections(matched, orderedDepts), [matched, orderedDepts])
  // 展开状态里可能留着已经删空的分组：渲染时按当前存在的分组过滤一遍，不必在删除处逐个清理
  const visibleKeys = useMemo(
    () => new Set(sections.flatMap((section) => section.groups.map((group) => group.key))),
    [sections],
  )

  const deptCount = useMemo(() => new Set(scoped.map((item) => item.department)).size, [scoped])
  // 未指定岗位的分组不算「岗位」，单独点出来
  const [groupCount, hasUnassigned] = useMemo(
    () => sections.reduce(
      ([count, unassigned], section) => {
        const real = section.groups.filter((group) => group.position !== null).length
        return [count + real, unassigned || real < section.groups.length]
      },
      [0, false] as [number, boolean],
    ),
    [sections],
  )
  const positionsLabel = [groupCount > 0 ? `${groupCount} 个岗位` : '', hasUnassigned ? '未指定岗位' : '']
    .filter(Boolean)
    .join('及')
  const joinParts = (...parts: string[]) => parts.filter(Boolean).join(' · ')
  // 首屏数据没回来之前没有可报的数，先不显示，免得闪一下「0 条」
  const summary = loading && items.length === 0
    ? ''
    : searching
      ? (positionsLabel
        ? `找到 ${matched.length} 条 SOP，分布在 ${positionsLabel}`
        : '没有找到匹配的 SOP')
      : activeDept
        ? joinParts(positionsLabel, `${matched.length} 条 SOP`)
        : joinParts(`${matched.length} 条 SOP`, `${deptCount} 个部门`, positionsLabel)

  const selectDept = (name: string | null) => {
    setActiveDept(name)
    setKeyword('')
  }

  // 新增弹窗的岗位、部门选项是首屏加载的：这期间可能在「岗位管理」里加过岗位，
  // 打开弹窗时刷新一次，不然选不到新岗位（要刷新页面才出来）
  const openCreateForm = () => {
    setFormOpen(true)
    void Promise.allSettled([fetchPositions(), fetchTrainingDepartmentOptions()]).then(([posRes, deptRes]) => {
      if (posRes.status === 'fulfilled') setPositions(posRes.value)
      if (deptRes.status === 'fulfilled') setDepartments(deptRes.value.data)
    })
  }

  const handleDelete = async (item: SopCatalogItem) => {
    setDeletingIds((ids) => [...ids, item.id])
    try {
      await deleteSopItem(item.id)
      // 页面只展示目录条目（联动的岗位培训内容不在页面上），删成功后本地移除即可，不必重拉
      setItems((prev) => prev.filter((it) => it.id !== item.id))
      message.success(`已删除「${item.file_name}」`)
    } catch (err) {
      message.error(errText(err, '删除失败'))
    } finally {
      setDeletingIds((ids) => ids.filter((id) => id !== item.id))
    }
  }

  const handleClear = async (group: SopGroup) => {
    setClearingKey(group.key)
    const results = await Promise.allSettled(group.items.map((item) => deleteSopItem(item.id)))
    // 逐条删，成功的才算删掉；有失败的留在页面上，提示重试
    const removed = new Set<string>()
    group.items.forEach((item, index) => {
      if (results[index].status === 'fulfilled') removed.add(item.id)
    })
    if (removed.size > 0) setItems((prev) => prev.filter((item) => !removed.has(item.id)))
    setClearingKey(null)
    const failed = group.items.length - removed.size
    const label = group.position ?? '未指定岗位'
    if (failed > 0) message.error(`「${label}」：${removed.size} 条已删除，${failed} 条删除失败，请重试`)
    else message.success(`已清空「${label}」的培训内容`)
  }

  // 上传可能动到任何部门，只能整表重拉；期间旧列表照常显示
  const handleUpload = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    setUploading(true)
    try {
      const res = await uploadSopCatalog(fd)
      const errors = res.data?.errors ?? []
      if (errors.length > 0) {
        modal.warning({
          title: `上传完成，${errors.length} 条未导入`,
          width: 560,
          content: (
            <ul className={styles.errorList}>
              {errors.map((error, index) => <li key={index}>{error}</li>)}
            </ul>
          ),
        })
      }
      message.success(`上传完成：新增 ${res.data.created} 条，更新 ${res.data.updated} 条`)
      setRefreshing(true)
      try {
        const fresh = await fetchAllSopCatalog()
        setItems(fresh.data)
      } catch {
        message.error('目录已更新，但列表刷新失败，请刷新页面')
      } finally {
        setRefreshing(false)
      }
    } catch (err) {
      message.error(errText(err, '上传失败'))
    } finally {
      setUploading(false)
    }
  }

  const uploadButton = (
    <Upload
      accept=".xlsx,.docx"
      showUploadList={false}
      beforeUpload={(file) => {
        if (!/\.(xlsx|docx)$/i.test(file.name)) {
          message.error('仅支持 .xlsx / .docx；旧版 .doc / .xls 请先用 Office 另存为新格式')
          return Upload.LIST_IGNORE
        }
        return true
      }}
      customRequest={({ file, onSuccess, onError }) => {
        // 上传入口已按扩展名校验过，走到这里的 file 一定是 File
        handleUpload(file as File).then(() => onSuccess?.({}), (err: Error) => onError?.(err))
      }}
    >
      <Tooltip title="支持 Excel(.xlsx) 或 GMP 文件目录 Word(.docx)，自动解析培训类别与 SOP 编号；旧版 .doc / .xls 请先用 Office 另存">
        <Button icon={<UploadOutlined />} loading={uploading}>上传SOP目录</Button>
      </Tooltip>
    </Upload>
  )

  // 接口只回岗位培训行的 id（和目录条目不是同一张表），新条目要重拉该部门才能拿到
  const handleCreated = async (created: CreatedSopItem) => {
    // 切到新增内容所在的部门、清掉搜索并展开那一组，让它出现在眼前
    setActiveDept(created.department)
    setKeyword('')
    const key = groupKey(created.department, created.positionName)
    setExpandedKeys((keys) => (keys.includes(key) ? keys : [...keys, key]))
    try {
      const res = await fetchAllSopCatalog(created.department)
      setItems((prev) => [...prev.filter((item) => item.department !== created.department), ...res.data])
      const added = res.data.find((item) => item.position_name === created.positionName
        && item.file_name === created.fileName)
      if (added) {
        setHighlightItemId(added.id)
        if (highlightTimer.current) window.clearTimeout(highlightTimer.current)
        highlightTimer.current = window.setTimeout(() => setHighlightItemId(null), 2600)
      }
    } catch {
      message.error('已新增，但目录刷新失败，请刷新页面查看')
    }
  }

  // 新增的条目可能排在视野之外：数据到位后把它滚进来
  useEffect(() => {
    if (!highlightItemId) return
    scrollRef.current?.querySelector(`[data-sop-item="${highlightItemId}"]`)?.scrollIntoView({ block: 'center' })
  }, [highlightItemId, items, expandedKeys])

  useEffect(() => () => {
    if (highlightTimer.current) window.clearTimeout(highlightTimer.current)
  }, [])

  const centered = (node: ReactNode) => (
    <div className="flex h-full items-center justify-center">{node}</div>
  )

  let body: ReactNode
  if (loading && items.length === 0) {
    body = centered(<Spin />)
  } else if (loadFailed) {
    body = centered(
      <EmptyState
        icon={<WarningOutlined className="text-xl text-[var(--color-warning)]" />}
        title="SOP 目录加载失败"
        description="请稍后重试"
        action={(
          <Button onClick={() => { setLoading(true); setLoadFailed(false); setRetryTick((n) => n + 1) }}>
            重试
          </Button>
        )}
      />,
    )
  } else if (searching) {
    body = matched.length === 0
      ? centered(
        <EmptyState
          icon={<SearchOutlined className="text-xl text-[var(--color-brand-purple)]" />}
          title={`没有找到与「${keyword.trim()}」匹配的 SOP`}
          description="可以按岗位、培训类别、文件名称或 SOP 编号搜索"
          action={<Button onClick={() => setKeyword('')}>清除搜索</Button>}
        />,
      )
      : (
        <div className="px-4 py-3">
          {/* key 带上搜索范围：换词或换部门时表格重新挂载，页码回到第一页 */}
          <SopSearchTable
            key={`${activeDept ?? ''}|${kw}`}
            items={matched}
            keyword={kw}
            showDepartment={!activeDept}
            canManage={canManage}
            deletingIds={deletingIds}
            onDelete={(item) => { void handleDelete(item) }}
          />
        </div>
      )
  } else if (sections.length === 0) {
    body = centered(
      <EmptyState
        icon={<FolderOpenOutlined className="text-xl text-[var(--color-brand-purple)]" />}
        title={activeDept ? `「${activeDept}」还没有 SOP 目录` : '还没有 SOP 目录数据'}
        description="上传目录文件批量导入各部门、各岗位的培训内容，或手动新增一条；新员工入职培训从这里取培训内容"
        action={canManage ? (<>{uploadButton}<Button type="primary" icon={<PlusOutlined />} onClick={openCreateForm}>新增培训内容</Button></>) : undefined}
      />,
    )
  } else {
    body = (
      <div className="px-4 py-3">
        <SopGroupList
          sections={sections}
          expandedKeys={expandedKeys.filter((key) => visibleKeys.has(key))}
          onExpandedChange={setExpandedKeys}
          canManage={canManage}
          deletingIds={deletingIds}
          clearingKey={clearingKey}
          highlightItemId={highlightItemId}
          onDelete={(item) => { void handleDelete(item) }}
          onClear={(group) => { void handleClear(group) }}
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 xl:h-full">
      <PageHeader
        title="SOP目录"
        description="维护各部门、各岗位需要培训的 SOP 文件；新员工入职培训的培训内容从这里取"
        actions={canManage ? (
          <>
            {uploadButton}
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateForm}>
              新增培训内容
            </Button>
          </>
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
            {loading && items.length === 0 ? (
              <div className="pl-2 pr-10 pt-1">
                <Skeleton active title={false} paragraph={{ rows: 10 }} />
              </div>
            ) : (
              <ul className="flex flex-col gap-0.5">
                {navItems.map((item, index) => (
                  <li key={item.name ?? ALL}>
                    {/* 「全部部门」和具体部门之间隔一条线 */}
                    {index === 1 && <div aria-hidden className="my-2 border-t border-[var(--color-hairline)]" />}
                    <NavButton item={item} active={activeDept === item.name} onClick={() => selectDept(item.name)} />
                  </li>
                ))}
                {navItems.length === 1 && (
                  <li className="px-3 py-6 text-center text-[13px] text-[var(--color-stone)]">没有匹配的部门</li>
                )}
              </ul>
            )}
          </nav>
        </aside>

        {/* 右栏：所选范围内的岗位分组与条目 */}
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
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-0.5">
              <h2 className="truncate text-[16px] font-semibold leading-tight text-[var(--color-ink)]">
                {activeDept ?? '全部部门'}
              </h2>
              <span className="text-[13px] text-[var(--color-steel)]">{summary}</span>
              {refreshing && <Spin size="small" />}
            </div>
            <Input
              allowClear
              aria-label="搜索 SOP"
              prefix={<SearchOutlined />}
              placeholder="搜索岗位 / 类别 / 文件名 / SOP 编号"
              style={{ width: 'min(320px, 100%)' }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </header>

          <div ref={scrollRef} className={styles.scrollBody}>
            {body}
          </div>
        </section>
      </div>

      <SopItemFormModal
        open={formOpen}
        defaultDepartment={activeDept ?? undefined}
        departments={orderedDepts}
        items={items}
        positions={positions}
        onClose={() => setFormOpen(false)}
        onCreated={(created) => { void handleCreated(created) }}
      />
    </div>
  )
}
