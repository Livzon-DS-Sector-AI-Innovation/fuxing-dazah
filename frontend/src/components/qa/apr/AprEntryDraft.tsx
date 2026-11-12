'use client'

import { useState, useSyncExternalStore } from 'react'
import { Alert, Button, Space } from 'antd'
import type { EditKey, GridValue } from './AprEntryShared'

// ── 未保存草稿（localStorage）：覆盖刷新、崩溃与站内跳转 ─────────────

/** 行内编辑只存在内存里；按产品×段×年度存一份草稿，站内跳转/刷新后仍能找回。 */
export type EntryDraft = {
  v: 1
  edits: Record<EditKey, GridValue>
  labelEdits: Record<EditKey, string>
  extraRows: Record<string, number[]>
  removedRows: string[]
  savedAt: number
}

const DRAFT_PREFIX = 'qa:apr:entry-draft:'

/** 抽到组件外，避免 React Compiler 把 Date.now() 当作渲染期不纯调用。 */
export function draftTimestamp(): number {
  return Date.now()
}

export function draftKeyOf(productId: string, sectionId: string, year: number): string {
  return `${DRAFT_PREFIX}${productId}:${sectionId}:${year}`
}

function isGridValue(value: unknown): value is GridValue {
  if (!value || typeof value !== 'object') return false
  const cell = value as Partial<GridValue>
  return (
    (cell.num === null || typeof cell.num === 'number') &&
    typeof cell.raw === 'string' &&
    typeof cell.text === 'string'
  )
}

function parseDraft(raw: string | null): EntryDraft | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<EntryDraft>
    const savedAt = parsed.savedAt
    if (parsed.v !== 1 || typeof savedAt !== 'number' || !Number.isFinite(savedAt)) return null
    const edits: Record<EditKey, GridValue> = {}
    for (const [key, value] of Object.entries(parsed.edits ?? {})) {
      if (isGridValue(value)) edits[key] = value
    }
    const labelEdits: Record<EditKey, string> = {}
    for (const [key, value] of Object.entries(parsed.labelEdits ?? {})) {
      if (typeof value === 'string') labelEdits[key] = value
    }
    const extraRows: Record<string, number[]> = {}
    for (const [key, value] of Object.entries(parsed.extraRows ?? {})) {
      if (Array.isArray(value) && value.every((seq) => typeof seq === 'number')) {
        extraRows[key] = value
      }
    }
    const removedRows = Array.isArray(parsed.removedRows)
      ? parsed.removedRows.filter((key): key is string => typeof key === 'string')
      : []
    return { v: 1, edits, labelEdits, extraRows, removedRows, savedAt }
  } catch {
    return null
  }
}

/** useSyncExternalStore 的快照必须同一份数据保持同一引用，按原始字符串缓存。 */
const draftSnapshots = new Map<string, { raw: string | null; draft: EntryDraft | null }>()

function readDraftSnapshot(key: string): EntryDraft | null {
  if (typeof window === 'undefined') return null
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(key)
  } catch {
    return null
  }
  const cached = draftSnapshots.get(key)
  if (cached && cached.raw === raw) return cached.draft
  const draft = parseDraft(raw)
  draftSnapshots.set(key, { raw, draft })
  return draft
}

// 草稿只在挂载时取一次，不需要订阅跨标签页的 storage 事件。
function subscribeDraftSnapshot(): () => void {
  return () => {}
}

export function writeDraft(key: string, draft: EntryDraft): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(draft))
  } catch {
    // 隐私模式/配额满：丢草稿不能阻塞录入
  }
  draftSnapshots.delete(key)
}

export function removeDraft(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // ignore
  }
  draftSnapshots.delete(key)
}

/** 只保留当前仍存在的批次的键，避免恢复后出现「幽灵未保存批次」。 */
export function pruneDraft(draft: EntryDraft, batchIds: Set<string>): EntryDraft {
  const keep = (key: string) => batchIds.has(key.split('|')[0])
  return {
    ...draft,
    edits: Object.fromEntries(Object.entries(draft.edits).filter(([key]) => keep(key))),
    labelEdits: Object.fromEntries(
      Object.entries(draft.labelEdits).filter(([key]) => keep(key)),
    ),
    extraRows: Object.fromEntries(
      Object.entries(draft.extraRows).filter(([batchId]) => batchIds.has(batchId)),
    ),
    removedRows: draft.removedRows.filter(keep),
  }
}

export function draftChangeCount(draft: EntryDraft): number {
  return (
    Object.keys(draft.edits).length +
    Object.keys(draft.labelEdits).length +
    Object.values(draft.extraRows).reduce((count, seqs) => count + seqs.length, 0) +
    draft.removedRows.length
  )
}

/** 重新进入录入页时提示恢复上次未保存的行内编辑。 */
export function EntryDraftBanner({
  draftKey,
  batchIds,
  onRestore,
}: {
  draftKey: string
  batchIds: Set<string>
  onRestore: (draft: EntryDraft) => void
}) {
  const draft = useSyncExternalStore(
    subscribeDraftSnapshot,
    () => readDraftSnapshot(draftKey),
    () => null,
  )
  const [hidden, setHidden] = useState(false)
  if (hidden || !draft) return null
  const pruned = pruneDraft(draft, batchIds)
  const count = draftChangeCount(pruned)
  if (count === 0) return null
  const savedAt = new Date(draft.savedAt).toLocaleString('zh-CN', { hour12: false })
  return (
    <Alert
      type="warning"
      showIcon
      className="mb-3"
      title={`发现上次未保存的草稿：${count} 处修改（${savedAt}）`}
      description="恢复后需要重新保存；如果这些改动已经不需要了，可以直接丢弃。"
      action={
        <Space size={6}>
          <Button size="small" type="primary" onClick={() => onRestore(pruned)}>
            恢复草稿
          </Button>
          <Button
            size="small"
            onClick={() => {
              removeDraft(draftKey)
              setHidden(true)
            }}
          >
            丢弃
          </Button>
        </Space>
      }
    />
  )
}
