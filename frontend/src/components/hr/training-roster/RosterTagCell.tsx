'use client'

// 培训人员名单的「分类」单元格。标签随名单行下发（不再逐行补查），
// 点击在弹出面板里勾选；保存由父组件负责（乐观更新 + 失败还原），这里只收集用户意图。

import { useState } from 'react'
import { Button, Checkbox, Input, Popover, Tooltip } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { ClassificationChip, ColorDot, type ChipColor } from './classificationChip'
import type { EmployeeClassification } from '@/types/hr'

/** 单元格里最多平铺几个胶囊，其余折进「+N」（悬停可看全部） */
const MAX_CHIPS = 2

interface RosterTagCellProps {
  employeeNumber: string
  employeeName: string
  tags: string[]
  classifications: EmployeeClassification[]
  colorOf: (name: string) => ChipColor
  /** 勾选变化：父组件做乐观更新与保存，结束后（无论成败）返回 */
  onTagsChange: (employeeNumber: string, nextTags: string[]) => Promise<void>
  /** 面板里就地新建分类；成功返回 true（随后自动勾给该人），失败由父组件提示并返回 false */
  onCreateClassification: (name: string) => Promise<boolean>
}

export default function RosterTagCell({
  employeeNumber, employeeName, tags, classifications, colorOf, onTagsChange, onCreateClassification,
}: RosterTagCellProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  // 按分类清单顺序排（清单里的在前、残留标签在后），与面板、抽屉里的顺序一致
  const order = new Map(classifications.map((c, i) => [c.name, i]))
  const sorted = [...tags].sort(
    (a, b) =>
      (order.get(a) ?? Number.MAX_SAFE_INTEGER) - (order.get(b) ?? Number.MAX_SAFE_INTEGER)
      || a.localeCompare(b, 'zh-Hans-CN'),
  )
  const shown = sorted.slice(0, MAX_CHIPS)
  const rest = sorted.slice(MAX_CHIPS)

  const toggle = async (name: string, checked: boolean) => {
    if (busy) return
    setBusy(true)
    try {
      await onTagsChange(employeeNumber, checked ? [...tags, name] : tags.filter((t) => t !== name))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover
      trigger="click"
      placement="bottomLeft"
      open={open}
      onOpenChange={setOpen}
      arrow={false}
      styles={{ container: { padding: 0 } }}
      content={(
        <TagEditor
          employeeName={employeeName}
          tags={tags}
          classifications={classifications}
          colorOf={colorOf}
          busy={busy}
          onToggle={toggle}
          onCreate={onCreateClassification}
          onClose={() => setOpen(false)}
        />
      )}
    >
      <div
        role="button"
        tabIndex={0}
        aria-label={`编辑 ${employeeName} 的分类`}
        className="group/cell -mx-2 flex min-h-[26px] w-[calc(100%+16px)] cursor-pointer flex-wrap items-center gap-1 rounded-[var(--rounded-sm)] px-2 transition-colors hover:bg-[var(--color-surface)] focus-visible:outline-2 focus-visible:outline-[var(--color-primary)]"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((o) => !o)
          }
        }}
      >
        {tags.length === 0 ? (
          <span className="inline-flex h-[22px] items-center gap-1 rounded-[var(--rounded-xs)] border border-dashed border-[var(--color-hairline-strong)] px-1.5 text-[12px] leading-none text-[var(--color-steel)] transition-colors group-hover/cell:border-[var(--color-primary)] group-hover/cell:text-[var(--color-primary)]">
            <PlusOutlined className="text-[10px]" />
            分类
          </span>
        ) : (
          <>
            {shown.map((name) => (order.has(name) ? (
              <ClassificationChip key={name} name={name} color={colorOf(name)} />
            ) : (
              <Tooltip key={name} title="残留标签：该分类已从分类清单删除">
                <span>
                  <ClassificationChip name={name} color={colorOf(name)} orphan />
                </span>
              </Tooltip>
            )))}
            {rest.length > 0 && (
              <Tooltip title={rest.join('、')}>
                <span className="cursor-default text-[12px] leading-none text-[var(--color-steel)] tabular-nums">
                  +{rest.length}
                </span>
              </Tooltip>
            )}
            <span className="inline-flex size-[22px] items-center justify-center rounded-[var(--rounded-xs)] text-[var(--color-stone)] opacity-0 transition-opacity group-hover/cell:opacity-100">
              <PlusOutlined className="text-[10px]" />
            </span>
          </>
        )}
      </div>
    </Popover>
  )
}

interface TagEditorProps {
  employeeName: string
  tags: string[]
  classifications: EmployeeClassification[]
  colorOf: (name: string) => ChipColor
  busy: boolean
  onToggle: (name: string, checked: boolean) => void
  onCreate: (name: string) => Promise<boolean>
  onClose: () => void
}

/** 勾选面板：搜索 + 分类清单 + 就地新建 */
function TagEditor({
  employeeName, tags, classifications, colorOf, busy, onToggle, onCreate, onClose,
}: TagEditorProps) {
  const [keyword, setKeyword] = useState('')
  // 还没有分类时直接展开新建框，省一次点击
  const [creating, setCreating] = useState(classifications.length === 0)
  const [newName, setNewName] = useState('')
  const [createSaving, setCreateSaving] = useState(false)

  const known = new Set(classifications.map((c) => c.name))
  // 清单里已没有、这个人身上还挂着的标签（分类被删后的残留），置顶提示可清理
  const orphans = tags.filter((t) => !known.has(t))
  const kw = keyword.trim()
  const visible = kw
    ? classifications.filter((c) => c.name.toLowerCase().includes(kw.toLowerCase()))
    : classifications

  const submitCreate = async (name: string) => {
    const trimmed = name.trim()
    if (!trimmed || createSaving) return
    // 手输了一个已存在的分类名：不必新建，直接勾上
    if (known.has(trimmed)) {
      setNewName('')
      onToggle(trimmed, true)
      return
    }
    setCreateSaving(true)
    try {
      // 就地新建后自动勾给当前人员（在某个人的面板里新建，意图就是归入这个分类）
      if (await onCreate(trimmed)) {
        setNewName('')
        onToggle(trimmed, true)
      }
    } finally {
      setCreateSaving(false)
    }
  }

  return (
    <div
      className="w-[272px]"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onClose()
        }
      }}
    >
      <div className="truncate px-3 pt-2.5 pb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
        为「{employeeName}」选择分类
      </div>
      <div className="border-b border-[var(--color-hairline-soft)] px-2 pb-2">
        <Input
          size="small"
          allowClear
          autoFocus
          prefix={<SearchOutlined className="text-[var(--color-muted)]" />}
          placeholder="搜索分类"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>
      <div className="max-h-[252px] overflow-y-auto py-1">
        {orphans.map((name) => (
          <EditorRow
            key={name}
            checked
            disabled={busy}
            name={name}
            count="已停用"
            color={colorOf(name)}
            onClick={() => onToggle(name, false)}
          />
        ))}
        {visible.map((c) => (
          <EditorRow
            key={c.id}
            checked={tags.includes(c.name)}
            disabled={busy}
            name={c.name}
            count={`${c.count} 人`}
            color={colorOf(c.name)}
            onClick={() => onToggle(c.name, !tags.includes(c.name))}
          />
        ))}
        {kw && visible.length === 0 && (
          <button
            type="button"
            disabled={createSaving}
            onClick={() => { void submitCreate(kw) }}
            className="flex h-9 w-full cursor-pointer items-center gap-2.5 px-3 text-left text-[13px] text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] disabled:cursor-default"
          >
            <PlusOutlined className="text-[var(--color-primary)]" />
            新建分类「{kw}」
          </button>
        )}
        {!kw && orphans.length === 0 && classifications.length === 0 && (
          <p className="px-3 py-3 text-[13px] leading-relaxed text-[var(--color-steel)]">
            还没有分类，在下方新建一个即可勾选。
          </p>
        )}
      </div>
      <div className="border-t border-[var(--color-hairline-soft)] p-2">
        {creating ? (
          <div className="flex gap-2">
            <Input
              size="small"
              autoFocus
              maxLength={64}
              placeholder="新分类名称，回车新建"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onPressEnter={() => { void submitCreate(newName) }}
            />
            <Button size="small" type="primary" loading={createSaving} onClick={() => { void submitCreate(newName) }}>
              新建
            </Button>
          </div>
        ) : (
          <Button type="text" size="small" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            新建分类
          </Button>
        )}
      </div>
    </div>
  )
}

interface EditorRowProps {
  checked: boolean
  disabled?: boolean
  name: string
  count: string
  color: ChipColor
  onClick: () => void
}

function EditorRow({ checked, disabled, name, count, color, onClick }: EditorRowProps) {
  return (
    <div
      className={`flex h-9 items-center gap-2.5 px-3 hover:bg-[var(--color-surface)] ${disabled ? 'cursor-default' : 'cursor-pointer'}`}
      onClick={() => { if (!disabled) onClick() }}
    >
      <Checkbox
        checked={checked}
        disabled={disabled}
        aria-label={name}
        // 勾选框自己就是开关：拦住冒泡，避免和整行点击各触发一次
        onChange={(e) => { e.stopPropagation(); if (!disabled) onClick() }}
      />
      <ColorDot color={color} />
      <span className="flex-1 truncate text-[13px] text-[var(--color-charcoal)]">{name}</span>
      <span className="text-[12px] leading-none text-[var(--color-stone)] tabular-nums">{count}</span>
    </div>
  )
}
