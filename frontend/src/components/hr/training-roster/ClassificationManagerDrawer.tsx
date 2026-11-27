'use client'

// 培训人员分类管理抽屉：左栏分类清单（新建 / 改名 / 删除），右栏该分类下的人员
// （搜索 / 批量移除 / 添加人员）。人员通过同名标签归入分类，改名由后端同步标签。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { App, Button, Checkbox, Drawer, Input, Popconfirm, Select, Spin, Tooltip } from 'antd'
import {
  CheckOutlined, CloseOutlined, DeleteOutlined, EditOutlined, PlusOutlined,
  SearchOutlined, TagsOutlined, TeamOutlined, UserAddOutlined,
} from '@ant-design/icons'
import {
  createEmployeeClassification,
  deleteEmployeeClassification,
  fetchClassificationMembers,
  fetchTrainingRoster,
  removeClassificationMembers,
  renameEmployeeClassification,
  saveEmployeeTag,
} from '@/actions/hr'
import type { TrainingRosterRow } from '@/actions/hr/employeeSync'
import { useDebouncedCallback } from '@/hooks/hr'
import type { ClassificationMember, EmployeeClassification } from '@/types/hr'
import { ColorDot, type ChipColor } from './classificationChip'

/** 与后端分类名长度上限一致 */
const NAME_MAX = 64

function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback
}

interface ClassificationManagerDrawerProps {
  open: boolean
  classifications: EmployeeClassification[]
  colorOf: (name: string) => ChipColor
  onClose: () => void
  /** 任一写操作后刷新分类清单（人数会变）；返回 Promise 以便等刷新完成 */
  onChanged: () => Promise<void> | void
}

export default function ClassificationManagerDrawer({
  open, classifications, colorOf, onClose, onChanged,
}: ClassificationManagerDrawerProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      size={800}
      // 窄屏（平板）上不超过视口宽度，否则抽屉会横向溢出
      styles={{ wrapper: { maxWidth: '100vw' } }}
      title="分类管理"
      destroyOnHidden
      footer={
        <div className="flex justify-end">
          <Button onClick={onClose}>关闭</Button>
        </div>
      }
    >
      {/* 选中项 / 改名 / 选人等临时状态放内层：抽屉关闭即销毁，下次打开是干净状态 */}
      <ManagerBody classifications={classifications} colorOf={colorOf} onChanged={onChanged} />
    </Drawer>
  )
}

function ManagerBody({ classifications, colorOf, onChanged }: {
  classifications: EmployeeClassification[]
  colorOf: (name: string) => ChipColor
  onChanged: () => Promise<void> | void
}) {
  const { message } = App.useApp()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameBusyRef = useRef(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // 选中项已不在清单里（被删）时回落到第一项：派生即可，不需要 effect 同步
  const active = classifications.find((c) => c.id === selectedId) ?? classifications[0] ?? null

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name || creating) return
    setCreating(true)
    try {
      const r = await createEmployeeClassification(name)
      await onChanged()
      setSelectedId(r.data.id) // 新建后直接选中，右栏可以马上添加人员
      setNewName('')
      message.success(`分类「${r.data.name}」已新建`)
    } catch (err) {
      message.error(errText(err, '新增失败'))
    } finally {
      setCreating(false)
    }
  }

  const submitRename = async () => {
    const c = classifications.find((x) => x.id === renamingId)
    const next = renameValue.trim()
    if (!c || renameBusyRef.current) return
    if (!next || next === c.name) {
      setRenamingId(null)
      return
    }
    renameBusyRef.current = true
    try {
      await renameEmployeeClassification(c.id, next)
      await onChanged()
      message.success('分类已改名，该分类下人员的标签已同步')
    } catch (err) {
      message.error(errText(err, '保存失败'))
    } finally {
      renameBusyRef.current = false
      setRenamingId(null)
    }
  }

  const handleDelete = async (c: EmployeeClassification) => {
    setDeletingId(c.id)
    try {
      await deleteEmployeeClassification(c.id)
      await onChanged()
      message.success(`分类「${c.name}」已删除`)
    } catch (err) {
      message.error(errText(err, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div>
      <p className="text-[13px] leading-relaxed text-[var(--color-steel)]">
        按培训需要把人员归入分类（如「新员工」「特种作业」）。在名单里点击某人的「分类」也能直接勾选。
      </p>

      <div className="mt-4 grid min-h-[520px] grid-cols-[264px_minmax(0,1fr)] gap-4">
        {/* 左栏：新建 + 分类清单 */}
        <aside className="flex min-h-0 flex-col gap-3">
          <div className="flex gap-2">
            <Input
              allowClear
              maxLength={NAME_MAX}
              placeholder="新分类名称"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onPressEnter={() => { void handleCreate() }}
            />
            <Button type="primary" icon={<PlusOutlined />} loading={creating} onClick={() => { void handleCreate() }}>
              新建
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {classifications.length === 0 ? (
              <p className="px-3 py-8 text-center text-[13px] leading-relaxed text-[var(--color-stone)]">
                还没有分类，在上方输入名称新建第一个
              </p>
            ) : (
              classifications.map((c) => (
                <div
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={`group/item flex h-10 cursor-pointer items-center gap-2.5 rounded-[var(--rounded-md)] px-3 ${
                    active?.id === c.id ? 'bg-[var(--color-surface)]' : 'hover:bg-[var(--color-surface-soft)]'
                  }`}
                >
                  <ColorDot color={colorOf(c.name)} />
                  {renamingId === c.id ? (
                    <div className="flex min-w-0 flex-1 items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <Input
                        size="small"
                        autoFocus
                        maxLength={NAME_MAX}
                        aria-label="新的分类名称"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onPressEnter={() => { void submitRename() }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') setRenamingId(null)
                        }}
                      />
                      <Tooltip title="保存">
                        <Button
                          size="small" type="primary" aria-label="保存"
                          icon={<CheckOutlined />}
                          onClick={() => { void submitRename() }}
                        />
                      </Tooltip>
                      <Tooltip title="取消">
                        <Button
                          size="small" type="text" aria-label="取消"
                          icon={<CloseOutlined />}
                          onClick={() => setRenamingId(null)}
                        />
                      </Tooltip>
                    </div>
                  ) : (
                    <>
                      <span
                        className={`flex-1 truncate text-[14px] ${
                          active?.id === c.id ? 'font-medium text-[var(--color-ink)]' : 'text-[var(--color-charcoal)]'
                        }`}
                      >
                        {c.name}
                      </span>
                      <span className="text-[12px] leading-none text-[var(--color-stone)] tabular-nums group-hover/item:hidden">
                        {c.count} 人
                      </span>
                      {/* 改名 / 删除只在悬停时出现，平时只显示人数，清单保持安静 */}
                      <span
                        className="hidden items-center gap-0.5 group-hover/item:flex"
                        // 删除确认框挂在页面根部的浮层里，但 React 点击事件仍会沿组件树冒泡回这一行：
                        // 不截住的话，点确认框里的「删除」会先选中这个正要删除的分类，右栏随即拉它的人员 → 404
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Tooltip title="改名">
                          <Button
                            size="small" type="text" aria-label="改名"
                            icon={<EditOutlined />}
                            onClick={() => { setRenamingId(c.id); setRenameValue(c.name) }}
                          />
                        </Tooltip>
                        <Popconfirm
                          title={`删除分类「${c.name}」？`}
                          description={c.count > 0 ? `该分类下 ${c.count} 人将解除此分类，不影响员工档案。` : undefined}
                          okText="删除"
                          okButtonProps={{ danger: true }}
                          cancelText="取消"
                          onConfirm={() => { void handleDelete(c) }}
                        >
                          <Button
                            size="small" type="text" danger aria-label="删除分类"
                            icon={<DeleteOutlined />}
                            loading={deletingId === c.id}
                          />
                        </Popconfirm>
                      </span>
                    </>
                  )}
                </div>
              ))
            )}
          </div>
        </aside>

        {/* 右栏：选中分类的人员 */}
        <section className="min-w-0 rounded-[var(--rounded-lg)] border border-[var(--color-hairline)]">
          {active ? (
            <MemberPanel key={active.id} classification={active} colorOf={colorOf} onChanged={onChanged} />
          ) : (
            <div className="flex h-full min-h-[520px] flex-col items-center justify-center gap-2 px-6 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-[var(--color-tint-lavender)]">
                <TagsOutlined className="text-xl text-[var(--color-brand-purple)]" />
              </span>
              <p className="text-[14px] font-medium text-[var(--color-charcoal)]">还没有分类</p>
              <p className="text-[13px] text-[var(--color-steel)]">在左侧输入名称，新建第一个分类</p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

interface MemberPanelProps {
  classification: EmployeeClassification
  colorOf: (name: string) => ChipColor
  onChanged: () => Promise<void> | void
}

/** 某个分类下的人员。父级用 key={分类 id} 挂载：切换分类即重建，不残留上一个分类的勾选 */
function MemberPanel({ classification, colorOf, onChanged }: MemberPanelProps) {
  const { message } = App.useApp()
  const [members, setMembers] = useState<ClassificationMember[]>([])
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [removing, setRemoving] = useState(false)

  // 挂载即拉该分类的人员；成员面板按分类 id 重建，切换分类不会有旧数据残留
  useEffect(() => {
    let cancelled = false
    fetchClassificationMembers(classification.id)
      .then((r) => {
        if (cancelled) return
        setMembers(r.data || [])
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        message.error(errText(err, '获取人员失败'))
        setLoading(false)
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 每次渲染是新引用，进依赖会无限重拉
  }, [classification.id])

  // ── 添加人员：远程搜索名单 ──
  const [adding, setAdding] = useState(false)
  const [addingBusy, setAddingBusy] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [candidates, setCandidates] = useState<TrainingRosterRow[]>([])
  const [searching, setSearching] = useState(false)
  const searchSeq = useRef(0)

  /** 增减人员后重拉；勾选一并清空（已移除的人不应再留在所选里） */
  const reload = useCallback(async () => {
    try {
      const r = await fetchClassificationMembers(classification.id)
      setMembers(r.data || [])
      setSelected(new Set())
    } catch (err) {
      message.error(errText(err, '获取人员失败'))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 每次渲染是新引用，进依赖会无限重拉
  }, [classification.id])

  const searchRoster = useCallback(async (kw: string) => {
    // 请求序号守卫：慢请求晚归时丢弃，避免旧结果覆盖新关键词的结果
    const seq = ++searchSeq.current
    setSearching(true)
    try {
      const res = await fetchTrainingRoster({ keyword: kw || undefined, page: 1, page_size: 20 })
      if (seq !== searchSeq.current) return
      setCandidates(res.data || [])
    } catch {
      if (seq === searchSeq.current) setCandidates([])
    } finally {
      if (seq === searchSeq.current) setSearching(false)
    }
  }, [])

  const { run: debouncedSearch } = useDebouncedCallback(
    (kw: string) => { void searchRoster(kw) }, 250,
  )

  const openPicker = () => {
    setAdding(true)
    setPicked([])
    void searchRoster('')
  }

  const memberNos = useMemo(() => new Set(members.map((m) => m.employee_number)), [members])
  const pickerOptions = candidates
    .filter((r) => !memberNos.has(r.employee_number))
    .map((r) => ({
      value: r.employee_number,
      // 同名员工靠工号区分，已选的胶囊里也要带工号
      label: `${r.name}（${r.employee_number}）`,
      name: r.name,
      employee_number: r.employee_number,
      department: r.department,
      position: r.position ?? '',
    }))

  const submitAdd = async () => {
    if (!picked.length || addingBusy) return
    setAddingBusy(true)
    try {
      const results = await Promise.allSettled(picked.map((no) =>
        saveEmployeeTag({ employee_number: no, tag_name: classification.name, action: 'add' }),
      ))
      const okCount = results.filter((r) => r.status === 'fulfilled').length
      if (okCount) {
        await reload()
        await onChanged()
        setAdding(false)
      }
      setPicked([])
      if (okCount === picked.length) message.success(`已添加 ${okCount} 人`)
      else message.warning(`已添加 ${okCount} 人，${picked.length - okCount} 人未成功，请重试`)
    } catch (err) {
      message.error(errText(err, '添加失败'))
    } finally {
      setAddingBusy(false)
    }
  }

  const removeMembers = async (nos: string[]) => {
    if (!nos.length || removing) return
    setRemoving(true)
    try {
      const r = await removeClassificationMembers(classification.id, nos)
      await reload()
      await onChanged()
      message.success(r.message || `已移除 ${nos.length} 人`)
    } catch (err) {
      message.error(errText(err, '移除失败'))
    } finally {
      setRemoving(false)
    }
  }

  const toggle = (no: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(no)) next.delete(no)
      else next.add(no)
      return next
    })
  }

  const kw = keyword.trim().toLowerCase()
  const visible = kw
    ? members.filter((m) =>
        [m.name, m.employee_number, m.department, m.position]
          .some((v) => (v || '').toLowerCase().includes(kw)))
    : members
  const visibleNos = visible.map((m) => m.employee_number)
  const allSelected = visibleNos.length > 0 && visibleNos.every((no) => selected.has(no))
  const someSelected = !allSelected && visibleNos.some((no) => selected.has(no))

  return (
    <div>
      <div className="flex items-center gap-2.5 border-b border-[var(--color-hairline)] px-4 py-3">
        <ColorDot color={colorOf(classification.name)} className="size-2.5" />
        <span className="text-[15px] font-semibold text-[var(--color-charcoal)]">{classification.name}</span>
        {!loading && (
          <span className="text-[13px] text-[var(--color-stone)] tabular-nums">{members.length} 人</span>
        )}
        {!adding && (
          <Button
            className="ml-auto" size="small" icon={<UserAddOutlined />}
            onClick={openPicker}
          >
            添加人员
          </Button>
        )}
      </div>

      {adding && (
        // 搜索框独占一行：与按钮同行时太窄，已选的人会被挤成「+2 …」
        <div className="space-y-2 border-b border-[var(--color-hairline-soft)] bg-[var(--color-surface-soft)] px-4 py-3">
          <Select
            mode="multiple"
            showSearch={{ filterOption: false, onSearch: debouncedSearch }}
            autoFocus
            placeholder="输入姓名或工号搜索名单"
            style={{ width: '100%' }}
            value={picked}
            onChange={(v) => setPicked(v)}
            options={pickerOptions}
            loading={searching}
            notFoundContent={searching ? <Spin size="small" /> : '没有可添加的人员'}
            maxTagCount="responsive"
            popupMatchSelectWidth={false}
            optionRender={(opt) => (
              <div className="flex items-baseline gap-2">
                <span className="font-medium">{opt.data.name}</span>
                <span className="text-[12px] text-[var(--color-stone)] tabular-nums">{opt.data.employee_number}</span>
                <span className="ml-auto pl-6 text-[12px] text-[var(--color-steel)]">
                  {[opt.data.department, opt.data.position].filter(Boolean).join(' / ')}
                </span>
              </div>
            )}
          />
          <div className="flex items-center gap-2">
            <span className="mr-auto text-[12px] text-[var(--color-steel)]">
              {picked.length ? `已选 ${picked.length} 人` : `从名单中挑选要加入「${classification.name}」的人员`}
            </span>
            <Button type="text" onClick={() => { setAdding(false); setPicked([]) }}>
              取消
            </Button>
            <Button type="primary" loading={addingBusy} disabled={!picked.length} onClick={() => { void submitAdd() }}>
              添加{picked.length ? `（${picked.length}）` : ''}
            </Button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-4 border-b border-[var(--color-hairline-soft)] px-4 py-2">
        <Input
          size="small"
          allowClear
          prefix={<SearchOutlined className="text-[var(--color-muted)]" />}
          placeholder="搜索姓名、工号、部门"
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <div className="ml-auto flex items-center gap-3">
          {/* 全选只作用于当前搜索结果，与用户看到的范围一致 */}
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected}
            disabled={!visibleNos.length}
            onChange={(e) => {
              setSelected((prev) => {
                const next = new Set(prev)
                visibleNos.forEach((no) => { if (e.target.checked) next.add(no); else next.delete(no) })
                return next
              })
            }}
          >
            全选
          </Checkbox>
          <Button
            type="link" size="small" danger loading={removing}
            disabled={!selected.size}
            onClick={() => { void removeMembers(Array.from(selected)) }}
          >
            移除所选{selected.size ? `（${selected.size}）` : ''}
          </Button>
        </div>
      </div>

      <Spin spinning={loading}>
        {/* 加载中不渲染空状态：min-h 给转圈留出居中位置，避免「暂无人员」先闪一下 */}
        <div className="max-h-[440px] min-h-[120px] overflow-y-auto rounded-b-[var(--rounded-lg)]">
          {!loading && visible.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
              <TeamOutlined className="text-2xl text-[var(--color-muted)]" />
              <p className="text-[14px] font-medium text-[var(--color-charcoal)]">
                {members.length ? '没有匹配的人员' : '该分类下暂无人员'}
              </p>
              {!members.length && (
                <p className="text-[13px] text-[var(--color-steel)]">
                  点右上角「添加人员」，或到名单里给人员勾选这个分类
                </p>
              )}
            </div>
          ) : (
            visible.map((m) => (
              <div
                key={m.employee_number}
                onClick={() => toggle(m.employee_number)}
                className="group/member flex h-11 cursor-pointer items-center gap-3 border-b border-[var(--color-hairline-soft)] px-4 transition-colors last:border-b-0 hover:bg-[var(--color-surface)]"
              >
                <Checkbox
                  checked={selected.has(m.employee_number)}
                  aria-label={`选择 ${m.name}`}
                  // 勾选框自己就是开关：拦住冒泡，避免和整行点击各触发一次
                  onChange={(e) => { e.stopPropagation(); toggle(m.employee_number) }}
                />
                <span className="w-16 shrink-0 truncate text-[14px] font-medium text-[var(--color-charcoal)]">
                  {m.name}
                </span>
                <span className="w-[88px] shrink-0 text-[12px] leading-none text-[var(--color-stone)] tabular-nums">
                  {m.employee_number}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--color-steel)]">
                  {[m.department, m.position].filter(Boolean).join(' / ')}
                </span>
                <Button
                  type="link" size="small" danger loading={removing}
                  className="opacity-0 group-hover/member:opacity-100"
                  onClick={(e) => { e.stopPropagation(); void removeMembers([m.employee_number]) }}
                >
                  移除
                </Button>
              </div>
            ))
          )}
        </div>
      </Spin>
    </div>
  )
}
