'use client'

import { useEffect, useState, type KeyboardEvent } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tooltip,
} from 'antd'
import { DeleteOutlined, SaveOutlined, UndoOutlined } from '@ant-design/icons'
import type { ColumnType, ColumnsType } from 'antd/es/table'
import clsx from 'clsx'
import {
  actionError,
  EmptyState,
  qaPageStyle,
} from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { createAprBatch, deleteAprBatch, saveAprBatchValues } from '@/actions/qa-apr'
import { fetchAprProducts, fetchAprSections, fetchAprSummary } from '@/lib/api/qa-apr'
import type { AprItem, AprSummaryRow } from '@/types/qa-apr'
import {
  AprChromeStyles,
  AprMeta,
  AprScopeBar,
  AprSheet,
  AprStamp,
  AprValue,
  AprYearField,
} from './AprChrome'
import { confirmAsync, DANGER_OK_PROPS, DATA_KIND_LABEL } from './AprConfigShared'

// ═════════════════════════ 工具 ═════════════════════════

/** #min/#max 成对列的名称后缀展示。 */
function itemDisplayName(item: AprItem): string {
  if (item.code.endsWith('#min')) return `${item.name_cn} MIN`
  if (item.code.endsWith('#max')) return `${item.name_cn} MAX`
  return item.name_cn
}

/** 数值列只接受纯数字（允许负号、小数点与首尾空格），非法输入返回 null。 */
function parseNumeric(raw: string): number | null {
  const text = raw.trim()
  if (!text) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/** 数值格输入：先 NFKC 归一化（全角数字、＜、．等纠正为半角），解析成功走数值槽；
 *  其余文本原样保留，保存时按该列 quick_values 白名单拦截。 */
function numberCellPatch(raw: string): Pick<GridValue, 'num' | 'raw' | 'text'> {
  const normalized = raw.normalize('NFKC')
  const num = parseNumeric(normalized)
  return { num, raw: normalized, text: num == null ? normalized.trim() : '' }
}

/** 数值列文字结果是否合法：空值合法，非空必须命中该列快捷值白名单。 */
function cellTextInvalid(item: AprItem, cell: GridValue): boolean {
  const text = cell.text.trim()
  return cell.num == null && !!text && !item.quick_values.includes(text)
}

/** 单元格是否已填：数值/文字任一槽有值即算（数值列填未检出也算）。 */
function cellFilled(cell: GridValue | undefined): boolean {
  return cell?.num != null || !!cell?.text?.trim()
}

/** 前端 OOS/OOT 判定（与后端 classify_point 同口径），行内编辑实时着色用。 */
function classifyCell(item: AprItem, value: number): 'normal' | 'oot' | 'oos' {
  if (
    (item.spec_min != null && value < item.spec_min) ||
    (item.spec_max != null && value > item.spec_max)
  ) {
    return 'oos'
  }
  if (
    (item.oot_min != null && value < item.oot_min) ||
    (item.oot_max != null && value > item.oot_max)
  ) {
    return 'oot'
  }
  return 'normal'
}

/** 数值格当前判定：编辑值优先（改完立刻重新着色），否则用服务端判定。 */
function cellStatus(item: AprItem, cell: GridValue, server: 'normal' | 'oot' | 'oos' | null | undefined) {
  if (cell.num != null) return classifyCell(item, cell.num)
  return server ?? null
}

/** 数值单元格：raw 是输入框里的原文，num 是解析结果（非法/空则为 null）。 */
type GridValue = { num: number | null; raw: string; text: string }
/** 编辑键：`${batchId}|${itemId}|${rowSeq}`；行标签键：`${batchId}|${rowSeq}`。 */
type EditKey = string

/** 矩阵行：一批一行（multi_row 段按已录行号展开，server 为 null 的是未保存的新增行）。 */
type EntryRow = {
  batchId: string
  batchNo: string
  rowSeq: number
  rowLabel: string | null
  server: AprSummaryRow | null
  extra: boolean
}

/** 矩阵行 = 汇总行 + 本地加行（新行号创建时锁定，避免删行后重排错位）；
 *  加行插到该批最后一行之后，批次已不在汇总里（被删）的加行自然丢弃。 */
function buildEntryRows(
  rows: AprSummaryRow[] | undefined,
  extraRows: Record<string, number[]>,
): EntryRow[] {
  if (!rows?.length) return []
  return rows.flatMap((r, i) => {
    const base: EntryRow = {
      batchId: r.batch_id,
      batchNo: r.batch_no,
      rowSeq: r.row_seq,
      rowLabel: r.row_label,
      server: r,
      extra: false,
    }
    const atBatchEnd = i + 1 >= rows.length || rows[i + 1].batch_id !== r.batch_id
    const seqs = atBatchEnd ? extraRows[r.batch_id] : undefined
    if (!seqs?.length) return [base]
    return [
      base,
      ...seqs.map((rowSeq) => ({
        batchId: r.batch_id,
        batchNo: r.batch_no,
        rowSeq,
        rowLabel: null as string | null,
        server: null as AprSummaryRow | null,
        extra: true,
      })),
    ]
  })
}

function omitByPrefix<T>(record: Record<string, T>, prefix: string): Record<string, T> {
  const next: Record<string, T> = {}
  for (const [key, value] of Object.entries(record)) {
    if (!key.startsWith(prefix)) next[key] = value
  }
  return next
}

/** 清掉某批某行的全部单元格编辑（删行/删除批次后防脏键残留）。 */
function stripRowEdits(record: Record<EditKey, GridValue>, batchId: string, rowSeq: number) {
  const next: Record<EditKey, GridValue> = {}
  const tail = `|${rowSeq}`
  for (const [key, value] of Object.entries(record)) {
    if (key.startsWith(`${batchId}|`) && key.endsWith(tail) && key.split('|').length === 3) {
      continue
    }
    next[key] = value
  }
  return next
}

/** 回车 / Shift+回车：聚焦下/上一行同列的可编辑格（跳过已删行与只读格）。 */
function focusRowSibling(e: KeyboardEvent<HTMLInputElement>, col: string, step: 1 | -1) {
  // 输入法回车是确认候选词，不该跳格
  if (e.nativeEvent.isComposing) return
  const origin = e.currentTarget.closest('tr')
  let tr = (step > 0 ? origin?.nextElementSibling : origin?.previousElementSibling) as
    | HTMLElement
    | null
  while (tr) {
    const input = tr.querySelector<HTMLInputElement>(`input[data-apr-col="${col}"]`)
    if (input) {
      input.focus()
      return
    }
    tr = (step > 0 ? tr.nextElementSibling : tr.previousElementSibling) as HTMLElement | null
  }
}

// ═════════════════════════ 数据录入页 ═════════════════════════

export function AprEntryPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const router = useRouter()
  const { hasPermission } = usePermission()
  // 写按钮按 enter 码显隐：只读用户看不到登记/保存/删除，不必靠后端 403 兜底
  const canEnter = hasPermission('qa:apr:enter')
  const searchParams = useSearchParams()
  // 选择状态同步进 URL（?product=&section=&year=&keyword=），刷新/分享链接都能恢复现场；
  // 懒初始化只在首帧读一次 URL，之后以本地 state 为准，变更时再写回。
  const [productId, setProductId] = useState<string | null>(() => searchParams.get('product'))
  const [sectionId, setSectionId] = useState<string | null>(() => searchParams.get('section'))
  const [year, setYear] = useState<number>(() => {
    const raw = Number(searchParams.get('year'))
    return Number.isInteger(raw) && raw >= 2000 && raw <= 2100 ? raw : new Date().getFullYear()
  })
  const [keyword, setKeyword] = useState(() => searchParams.get('keyword') ?? '')

  // 行内编辑态：edits 是格子覆盖层（未保存），labelEdits/extraRows/removedRows 同理；
  // 服务端值始终是底稿，渲染与保存时 edits 优先，避免把查询结果镜像进 state。
  const [edits, setEdits] = useState<Record<EditKey, GridValue>>({})
  const [labelEdits, setLabelEdits] = useState<Record<EditKey, string>>({})
  const [extraRows, setExtraRows] = useState<Record<string, number[]>>({})
  const [removedRows, setRemovedRows] = useState<Set<string>>(new Set())
  const [cellErrors, setCellErrors] = useState<Record<EditKey, string>>({})
  const [savingBatchId, setSavingBatchId] = useState<string | null>(null)
  const [allSaving, setAllSaving] = useState(false)
  const [focusedKey, setFocusedKey] = useState<EditKey | null>(null)

  const [registerOpen, setRegisterOpen] = useState(false)
  const [registerSaving, setRegisterSaving] = useState(false)
  const [registerForm] = Form.useForm()

  /** 把局部改动合并进当前查询串；空值即删除该参数。 */
  const syncUrl = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [key, value] of Object.entries(patch)) {
      if (value == null || value === '') params.delete(key)
      else params.set(key, value)
    }
    const query = params.toString()
    router.replace(query ? `/qa/apr/entry?${query}` : '/qa/apr/entry', { scroll: false })
  }

  const productsQuery = useQuery({
    queryKey: ['qa', 'apr', 'products', 'active'],
    queryFn: () => fetchAprProducts(true),
  })
  const products = productsQuery.data ?? []
  // 进页默认选中：未选/URL 里的产品已删时回退到第一个启用产品（派生而非 state，
  // 不写回 URL，用户显式切换时才同步链接）。
  const activeProductId = products.some((p) => p.id === productId)
    ? productId
    : products.length > 0
      ? products[0].id
      : null

  const sectionsQuery = useQuery({
    queryKey: ['qa', 'apr', 'sections', activeProductId],
    queryFn: () => fetchAprSections(activeProductId!),
    enabled: !!activeProductId,
  })
  const sections = sectionsQuery.data ?? []
  const activeSectionId = sections.some((s) => s.id === sectionId)
    ? sectionId
    : sections.length > 0
      ? sections[0].id
      : null
  const currentSection = sections.find((s) => s.id === activeSectionId) ?? null

  // 矩阵数据直接用年终汇总接口（批次行 + 单元格值 + 列定义一次拿全；
  // 单段单年批次量级几十，与汇总页同口径不分页）。
  const summaryQuery = useQuery({
    queryKey: ['qa', 'apr', 'summary', activeProductId, year],
    queryFn: () => fetchAprSummary({ product_id: activeProductId!, year }),
    enabled: !!activeProductId,
  })
  const sectionPayload =
    summaryQuery.data?.sections.find((s) => s.id === activeSectionId) ?? null
  const locked = summaryQuery.data?.locked === true
  const items = sectionPayload?.items ?? []
  const multiRow = sectionPayload?.multi_row ?? currentSection?.multi_row ?? false

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'summary'] })
    void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'trend'] })
  }

  // 矩阵行构建抽成组件外纯函数；派生值直接计算，由 React Compiler 自动记忆化
  // （手写 useMemo 会被其判为「依赖可能被变异」而 bail out 报错）
  const entryRows = buildEntryRows(sectionPayload?.rows, extraRows)

  const keywordText = keyword.trim().toLowerCase()
  const visibleRows = keywordText
    ? entryRows.filter((r) => r.batchNo.toLowerCase().includes(keywordText))
    : entryRows
  const batchCount = new Set(entryRows.map((r) => r.batchId)).size

  /** 每批首行行号：操作列的批次级按钮（保存/加行/删除）挂在首行。 */
  const firstRowSeqOfBatch = entryRows.reduce((map, r) => {
    const cur = map.get(r.batchId)
    if (cur == null || r.rowSeq < cur) map.set(r.batchId, r.rowSeq)
    return map
  }, new Map<string, number>())

  /** 有未保存改动的批次：格子/行标签/加行/删行任一即算。 */
  const dirtyBatches = new Set<string>([
    ...Object.keys(edits).map((key) => key.split('|')[0]),
    ...Object.keys(labelEdits).map((key) => key.split('|')[0]),
    ...Object.entries(extraRows)
      .filter(([, seqs]) => seqs.length > 0)
      .map(([batchId]) => batchId),
    ...[...removedRows].map((key) => key.split('|')[0]),
  ])
  const hasDirty = dirtyBatches.size > 0

  // 刷新/关标签页会丢行内编辑，交给浏览器原生确认兜底
  useEffect(() => {
    if (!hasDirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [hasDirty])

  /** 切换产品/段/年度会清空行内编辑，先对未保存改动做一次确认。 */
  const guardDirty = (action: () => void) => {
    if (dirtyBatches.size === 0) {
      action()
      return
    }
    confirmAsync(modal, {
      title: '放弃未保存的改动？',
      content: `${dirtyBatches.size} 个批次还有未保存的改动，切换后这些改动会丢失。`,
      okText: '放弃并切换',
      cancelText: '留在本页',
      okButtonProps: DANGER_OK_PROPS,
      onOk: action,
    })
  }

  /** 切换产品/段/年度时清空全部本地编辑：不同段的格子键不同，留着只会脏读。 */
  const clearAllEdits = () => {
    setEdits({})
    setLabelEdits({})
    setExtraRows({})
    setRemovedRows(new Set())
    setCellErrors({})
    setFocusedKey(null)
  }

  const cellOf = (row: EntryRow, item: AprItem): GridValue => {
    const edited = edits[`${row.batchId}|${item.id}|${row.rowSeq}`]
    if (edited) return edited
    const cell = row.server?.cells[item.id]
    return {
      num: cell?.num ?? null,
      raw: cell?.num != null ? String(cell.num) : (cell?.text ?? ''),
      text: cell?.text ?? '',
    }
  }

  const setCell = (key: EditKey, patch: GridValue) => {
    setEdits((prev) => ({ ...prev, [key]: patch }))
    setCellErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const clearBatchLocalState = (batchId: string) => {
    setEdits((prev) => omitByPrefix(prev, `${batchId}|`))
    setLabelEdits((prev) => omitByPrefix(prev, `${batchId}|`))
    setExtraRows((prev) => ({ ...prev, [batchId]: [] }))
    setRemovedRows((prev) => {
      const next = new Set(prev)
      for (const key of prev) if (key.startsWith(`${batchId}|`)) next.delete(key)
      return next
    })
    setCellErrors((prev) => omitByPrefix(prev, `${batchId}|`))
  }

  /** 整批保存：全量替换语义，把该批各行的当前值（edits 优先于服务端）整体提交。 */
  const saveBatch = async (batchId: string, batchNo: string): Promise<boolean> => {
    if (!sectionPayload || savingBatchId) return false
    const batchRows = entryRows.filter(
      (r) => r.batchId === batchId && !removedRows.has(`${batchId}|${r.rowSeq}`),
    )
    // 必填预检（与后端同口径）：单行段校验第 1 行；多行段校验有内容的行，全空回退第 1 行。
    const contentRows = batchRows.filter((r) => items.some((it) => cellFilled(cellOf(r, it))))
    const checkRows = multiRow
      ? contentRows.length
        ? contentRows
        : batchRows.filter((r) => r.rowSeq === 1)
      : batchRows.filter((r) => r.rowSeq === 1)
    const errors: Record<EditKey, string> = {}
    for (const row of checkRows) {
      for (const item of items) {
        if (!item.required) continue
        if (!cellFilled(cellOf(row, item))) {
          errors[`${batchId}|${item.id}|${row.rowSeq}`] = '必填项未填写'
        }
      }
    }
    if (Object.keys(errors).length > 0) {
      setCellErrors((prev) => ({ ...prev, ...errors }))
      message.error(`${batchNo} 有 ${Object.keys(errors).length} 个必填项未填写`)
      return false
    }
    // 数值列文字结果必须命中该列快捷值白名单（后端保存时同口径兜底）
    const invalidErrors: Record<EditKey, string> = {}
    for (const row of batchRows) {
      for (const item of items) {
        if (item.value_type !== 'number') continue
        if (!cellTextInvalid(item, cellOf(row, item))) continue
        invalidErrors[`${batchId}|${item.id}|${row.rowSeq}`] =
          item.quick_values.length > 0
            ? `只能填数字或：${item.quick_values.join('、')}`
            : '只能填数字（该列未配置文字结果）'
      }
    }
    if (Object.keys(invalidErrors).length > 0) {
      setCellErrors((prev) => ({ ...prev, ...invalidErrors }))
      message.error(`${batchNo} 有 ${Object.keys(invalidErrors).length} 处文字结果不在该列允许范围内`)
      return false
    }
    const values: {
      item_id: string
      row_seq: number
      row_label?: string | null
      value_num?: number | null
      value_text?: string | null
    }[] = []
    for (const row of batchRows) {
      for (const item of items) {
        const cell = cellOf(row, item)
        if (cell.num === null && !cell.text.trim()) continue
        const label = (labelEdits[`${batchId}|${row.rowSeq}`] ?? row.rowLabel ?? '').trim()
        values.push({
          item_id: item.id,
          row_seq: row.rowSeq,
          row_label: label || null,
          value_num: item.value_type === 'number' ? cell.num : null,
          value_text:
            item.value_type === 'text' || cell.num == null ? cell.text || null : null,
        })
      }
    }
    setSavingBatchId(batchId)
    try {
      const result = await saveAprBatchValues(batchId, values)
      if (!result.success) {
        message.error(actionError(result))
        return false
      }
      message.success(`已保存 ${batchNo} 的数据（${result.data?.saved ?? 0} 项）`)
      clearBatchLocalState(batchId)
      invalidate()
      return true
    } finally {
      setSavingBatchId(null)
    }
  }

  /** 全部保存：按当前顺序逐批提交，某批失败即停；未提交的批次保留本地改动。 */
  const saveAllBatches = async () => {
    if (!sectionPayload || allSaving) return
    const targets = entryRows.reduce<{ id: string; no: string }[]>((list, row) => {
      if (dirtyBatches.has(row.batchId) && !list.some((t) => t.id === row.batchId)) {
        list.push({ id: row.batchId, no: row.batchNo })
      }
      return list
    }, [])
    setAllSaving(true)
    try {
      for (const target of targets) {
        if (!(await saveBatch(target.id, target.no))) break
      }
    } finally {
      setAllSaving(false)
    }
  }

  const resetAllEdits = () => {
    confirmAsync(modal, {
      title: '放弃未保存的改动？',
      content: `${dirtyBatches.size} 个批次还有未保存的改动，还原后这些改动会丢失。`,
      okText: '放弃并还原',
      cancelText: '继续编辑',
      okButtonProps: DANGER_OK_PROPS,
      onOk: clearAllEdits,
    })
  }

  const handleRegister = async () => {
    let values: { year: number; batch_no: string; seq?: number; remark?: string }
    try {
      values = await registerForm.validateFields()
    } catch {
      return
    }
    setRegisterSaving(true)
    try {
      const result = await createAprBatch({
        section_id: activeSectionId!,
        year: values.year,
        batch_no: values.batch_no.trim(),
        seq: values.seq ?? undefined,
        remark: values.remark || undefined,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('批次已登记')
      setRegisterOpen(false)
      registerForm.resetFields()
      invalidate()
    } finally {
      setRegisterSaving(false)
    }
  }

  const handleDelete = (batchId: string, batchNo: string) => {
    confirmAsync(modal, {
      title: '删除批次',
      content: `将删除批次 ${batchNo} 及其全部录入值，且不可恢复。`,
      okButtonProps: DANGER_OK_PROPS,
      okText: '删除',
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteAprBatch(batchId)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('批次已删除')
        clearBatchLocalState(batchId)
        invalidate()
      },
    })
  }

  const addRow = (batchId: string) => {
    setExtraRows((prev) => {
      const existing = entryRows.filter((r) => r.batchId === batchId)
      const maxSeq = existing.reduce((acc, r) => Math.max(acc, r.rowSeq), 0)
      return { ...prev, [batchId]: [...(prev[batchId] ?? []), maxSeq + 1] }
    })
  }

  const removeRow = (row: EntryRow) => {
    if (row.extra) {
      setExtraRows((prev) => ({
        ...prev,
        [row.batchId]: (prev[row.batchId] ?? []).filter((s) => s !== row.rowSeq),
      }))
      setEdits((prev) => stripRowEdits(prev, row.batchId, row.rowSeq))
      setLabelEdits((prev) => {
        const next = { ...prev }
        delete next[`${row.batchId}|${row.rowSeq}`]
        return next
      })
    } else {
      // 已落库的行靠「保存时整批全量替换」真正删除：先本地标记隐藏，保存后生效
      setRemovedRows((prev) => new Set(prev).add(`${row.batchId}|${row.rowSeq}`))
    }
  }

  // ═════════════════════════ 矩阵渲染 ═════════════════════════

  // 全部保存期间锁住编辑，避免逐批提交时新输入落在已保存快照之外
  const readOnly = locked || !canEnter || allSaving

  const renderCell = (item: AprItem, row: EntryRow) => {
    const key = `${row.batchId}|${item.id}|${row.rowSeq}`
    const cell = cellOf(row, item)
    const removed = removedRows.has(`${row.batchId}|${row.rowSeq}`)
    const error = cellErrors[key]
    const status = cellStatus(item, cell, row.server?.cells[item.id]?.status)
    const color =
      status === 'oos' ? 'var(--color-error)' : status === 'oot' ? 'var(--color-warning)' : undefined
    const invalid = item.value_type === 'number' && cellTextInvalid(item, cell)

    if (readOnly || removed) {
      return (
        <AprValue
          value={cell.num ?? cell.text ?? ''}
          status={removed ? null : status}
          unit={cell.num != null ? item.unit : null}
        />
      )
    }
    if (item.value_type === 'text') {
      return (
        <Input
          variant="borderless"
          size="small"
          maxLength={300}
          style={{ width: '100%', color }}
          status={error ? 'error' : undefined}
          title={error ?? '文字判定，如 符合规定 / 未检出'}
          value={cell.text}
          data-apr-col={item.id}
          onPressEnter={(e) => focusRowSibling(e, item.id, e.shiftKey ? -1 : 1)}
          onChange={(e) => setCell(key, { num: null, raw: e.target.value, text: e.target.value })}
        />
      )
    }
    return (
      <Input
        variant="borderless"
        size="small"
        style={{ width: '100%', color }}
        status={error || invalid ? 'error' : undefined}
        title={
          error ??
          (invalid
            ? `只能填数字或：${item.quick_values.join('、') || '（该列未配置文字结果）'}`
            : undefined)
        }
        inputMode="decimal"
        value={cell.raw}
        data-apr-col={item.id}
        onPressEnter={(e) => focusRowSibling(e, item.id, e.shiftKey ? -1 : 1)}
        onFocus={() => setFocusedKey(key)}
        onBlur={() => setFocusedKey((k) => (k === key ? null : k))}
        // suffix 容器必须常驻、只切换内部内容：聚焦时动态增删 suffix 会改变
        // DOM 结构导致输入框失焦（antd 官方已知行为）。快捷标签仅在聚焦且为空的格子出现，
        // 已有值时让位给数值和单位，避免窄列里按钮把输入内容挤没。
        suffix={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {focusedKey === key && !cell.raw.trim()
              ? item.quick_values.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={AprChromeStyles.ndQuick}
                    aria-label={`填入${value}`}
                    title={`${value}（原样保留，统计口径由列定义决定）`}
                    // 阻止 mousedown 抢焦点，点击后输入框保持聚焦状态
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => setCell(key, { num: null, raw: value, text: value })}
                  >
                    {value}
                  </button>
                ))
              : null}
            {item.unit && (cell.num != null || !cell.raw.trim()) ? (
              <span className={AprChromeStyles.unit}>{item.unit}</span>
            ) : null}
          </span>
        }
        onChange={(e) => setCell(key, numberCellPatch(e.target.value))}
      />
    )
  }

  const itemColumn = (item: AprItem, groupStart = false): ColumnType<EntryRow> => ({
    key: item.id,
    title: (
      <div style={{ lineHeight: 1.35 }} title={item.required ? '必填项' : undefined}>
        <span style={{ whiteSpace: 'normal' }}>
          {item.required && (
            <span aria-hidden style={{ marginRight: 2, color: 'var(--color-error)' }}>
              *
            </span>
          )}
          {itemDisplayName(item)}
        </span>
        <div style={{ fontSize: 11, color: 'var(--color-steel)', whiteSpace: 'normal' }}>
          {item.spec_text || (item.unit ?? '')}
        </div>
      </div>
    ),
    width: 140,
    align: 'center',
    // 组界放在列左侧：表头、表体都不画逐格竖线，只留分组结构线
    onHeaderCell: groupStart ? () => ({ className: AprChromeStyles.groupStart }) : undefined,
    // 有未保存编辑的格子铺淡琥珀底，与操作列「保存」呼应
    onCell: (row) => ({
      className:
        clsx(
          edits[`${row.batchId}|${item.id}|${row.rowSeq}`] != null && AprChromeStyles.cellDirty,
          groupStart && AprChromeStyles.groupStart,
        ) || undefined,
      style: { padding: '4px 8px' },
    }),
    render: (_v, row) => renderCell(item, row),
  })

  /** 相邻同组列合并成二级表头，保持模板里的原始顺序；单列组也保留组名。 */
  const buildItemColumns = (cols: AprItem[]): ColumnsType<EntryRow> => {
    const result: ColumnsType<EntryRow> = []
    let i = 0
    while (i < cols.length) {
      const group = cols[i].group_name
      const groupStart = i > 0 && group !== cols[i - 1].group_name
      if (group) {
        let j = i
        while (j < cols.length && cols[j].group_name === group) j++
        result.push({
          title: group,
          // 组名统一贴组首：居中的宽组会被右侧固定列压住，看不到组名
          align: 'left',
          onHeaderCell: groupStart ? () => ({ className: AprChromeStyles.groupStart }) : undefined,
          children: cols.slice(i, j).map((item, offset) => itemColumn(item, offset === 0 && groupStart)),
        })
        i = j
        continue
      }
      result.push(itemColumn(cols[i], groupStart))
      i += 1
    }
    return result
  }

  const columns: ColumnsType<EntryRow> = [
    {
      title: '序号',
      key: 'row_index',
      width: 56,
      align: 'center',
      fixed: 'left',
      render: (_v, _r, index) => <span className={AprChromeStyles.rowIndex}>{index + 1}</span>,
    },
    {
      title: '批号',
      dataIndex: 'batchNo',
      width: 150,
      align: 'center',
      fixed: 'left',
      render: (value: string, row) => {
        const removed = removedRows.has(`${row.batchId}|${row.rowSeq}`)
        const dirty =
          dirtyBatches.has(row.batchId) && firstRowSeqOfBatch.get(row.batchId) === row.rowSeq
        return (
          <span
            className={clsx(AprChromeStyles.batchNo, dirty && AprChromeStyles.batchDirty)}
            title={dirty ? '该批次有未保存的改动' : undefined}
            style={removed ? { textDecoration: 'line-through', opacity: 0.55 } : undefined}
          >
            {value}
          </span>
        )
      },
    },
    ...(multiRow
      ? [
          {
            title: '行',
            key: 'row_label',
            width: 108,
            fixed: 'left' as const,
            onCell: () => ({ style: { padding: '4px 8px' } }),
            render: (_v: unknown, row: EntryRow) => {
              if (readOnly || removedRows.has(`${row.batchId}|${row.rowSeq}`)) {
                return <span style={{ fontSize: 12 }}>{row.rowLabel || `第 ${row.rowSeq} 行`}</span>
              }
              const key = `${row.batchId}|${row.rowSeq}`
              return (
                <Input
                  variant="borderless"
                  size="small"
                  maxLength={32}
                  style={{ width: '100%' }}
                  placeholder={`第 ${row.rowSeq} 行`}
                  value={labelEdits[key] ?? row.rowLabel ?? ''}
                  data-apr-col="__label"
                  onPressEnter={(e) => focusRowSibling(e, '__label', e.shiftKey ? -1 : 1)}
                  onChange={(e) =>
                    setLabelEdits((prev) => ({ ...prev, [key]: e.target.value }))
                  }
                />
              )
            },
          } satisfies ColumnType<EntryRow>,
        ]
      : []),
    ...buildItemColumns(items),
    {
      title: '操作',
      key: 'actions',
      width: 156,
      align: 'center',
      fixed: 'right',
      onCell: () => ({ style: { padding: '4px 8px', whiteSpace: 'nowrap' } }),
      render: (_v, row) => {
        const removed = removedRows.has(`${row.batchId}|${row.rowSeq}`)
        if (removed) {
          return (
            <Button
              type="link"
              size="small"
              onClick={() =>
                setRemovedRows((prev) => {
                  const next = new Set(prev)
                  next.delete(`${row.batchId}|${row.rowSeq}`)
                  return next
                })
              }
            >
              撤销删行
            </Button>
          )
        }
        const isFirst = firstRowSeqOfBatch.get(row.batchId) === row.rowSeq
        if (!isFirst) {
          // 非首行只承担 multi_row 的删行（保存时全量替换才真正落库）
          return multiRow && canEnter && !locked ? (
            <Button type="link" size="small" danger onClick={() => removeRow(row)}>
              删行
            </Button>
          ) : null
        }
        const dirty = dirtyBatches.has(row.batchId)
        return (
          <Space size={0}>
            {canEnter && !locked && dirty && (
              <>
                <Tooltip title="保存本批次的未保存改动">
                  <Button
                    type="primary"
                    size="small"
                    icon={<SaveOutlined />}
                    aria-label="保存本批次"
                    loading={savingBatchId === row.batchId}
                    // 同一时刻只保存一批，其他批的保存按钮先让路，避免点了没反应
                    disabled={allSaving || (savingBatchId !== null && savingBatchId !== row.batchId)}
                    onClick={() => void saveBatch(row.batchId, row.batchNo)}
                  />
                </Tooltip>
                <Tooltip title="还原本批次的未保存改动">
                  <Button
                    type="text"
                    size="small"
                    icon={<UndoOutlined />}
                    aria-label="还原本批次"
                    disabled={allSaving || savingBatchId !== null}
                    onClick={() => clearBatchLocalState(row.batchId)}
                  />
                </Tooltip>
              </>
            )}
            {canEnter && !locked && multiRow && (
              <Button type="link" size="small" onClick={() => addRow(row.batchId)}>
                加行
              </Button>
            )}
            {canEnter && !locked && (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label="删除批次"
                title="删除批次"
                onClick={() => handleDelete(row.batchId, row.batchNo)}
              />
            )}
          </Space>
        )
      },
    },
  ]

  const scrollX = (multiRow ? 470 : 362) + items.length * 140

  return (
    <div style={qaPageStyle}>
      <PageHeading
        title="数据录入"
        subtitle="按产品模板逐批登记批号，在表格里直接填写工艺参数与检验结果。年度定稿后不可修改。"
      />

      {productsQuery.isError && (
        <Alert
          type="error"
          showIcon
          className="mb-3"
          title="产品列表加载失败"
          description={productsQuery.error instanceof Error ? productsQuery.error.message : '请稍后重试'}
          action={
            <Button size="small" onClick={() => void productsQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}
      {activeProductId && sectionsQuery.isError && (
        <Alert
          type="error"
          showIcon
          className="mb-3"
          title="模板段加载失败"
          description={sectionsQuery.error instanceof Error ? sectionsQuery.error.message : '请稍后重试'}
          action={
            <Button size="small" onClick={() => void sectionsQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}
      {activeSectionId && summaryQuery.isError && (
        <Alert
          type="error"
          showIcon
          className="mb-3"
          title="批次数据加载失败"
          description={summaryQuery.error instanceof Error ? summaryQuery.error.message : '请稍后重试'}
          action={
            <Button size="small" onClick={() => void summaryQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}

      <AprScopeBar
        lead={
          <>
            <Select
              style={{ width: 216 }}
              placeholder="选择产品"
              showSearch
              optionFilterProp="label"
              value={activeProductId}
              onChange={(v) => {
                guardDirty(() => {
                  setProductId(v)
                  setSectionId(null)
                  clearAllEdits()
                  syncUrl({ product: v, section: null })
                })
              }}
              loading={productsQuery.isLoading}
              options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
            />
            <Select
              style={{ width: 236 }}
              placeholder="选择模板段"
              value={activeSectionId}
              onChange={(v) => {
                guardDirty(() => {
                  setSectionId(v)
                  clearAllEdits()
                  syncUrl({ section: v })
                })
              }}
              disabled={!activeProductId}
              loading={sectionsQuery.isLoading}
              options={sections.map((s) => ({
                value: s.id,
                label: s.market ? `${s.name}（${s.market}）` : s.name,
              }))}
            />
          </>
        }
        tail={
          <>
            <AprYearField
              value={year}
              onChange={(v) => {
                guardDirty(() => {
                  setYear(v)
                  clearAllEdits()
                  syncUrl({ year: String(v) })
                })
              }}
            />
            <Input.Search
              placeholder="按批号筛选"
              style={{ width: 200 }}
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onSearch={(v) => {
                setKeyword(v)
                syncUrl({ keyword: v || null })
              }}
            />
          </>
        }
      />

      <AprSheet
        title="批次录入矩阵"
        meta={
          <AprMeta
            items={[
              `${year} 年度`,
              currentSection ? currentSection.name : '未选模板段',
              currentSection && DATA_KIND_LABEL[currentSection.data_kind],
              currentSection?.market,
              activeSectionId ? `共 ${batchCount} 批` : false,
              locked ? '已定稿' : false,
            ]}
          />
        }
        actions={
          <Space size={6}>
            {hasDirty && <AprStamp tone="warn">{dirtyBatches.size} 批未保存</AprStamp>}
            {hasDirty && (
              <Button
                size="small"
                disabled={allSaving || savingBatchId !== null}
                onClick={resetAllEdits}
              >
                还原
              </Button>
            )}
            {hasDirty && canEnter && !locked && (
              <Button
                type="primary"
                size="small"
                loading={allSaving}
                disabled={!allSaving && savingBatchId !== null}
                onClick={() => void saveAllBatches()}
              >
                全部保存
              </Button>
            )}
            {currentSection?.multi_row && <AprStamp tone="warn">一批多行</AprStamp>}
            {locked && <AprStamp tone="locked">年度已定稿</AprStamp>}
            {canEnter && (
              <Button type="primary" disabled={!activeSectionId || locked} onClick={() => setRegisterOpen(true)}>
                登记批次
              </Button>
            )}
          </Space>
        }
        footer={
          <>
            <span>
              直接在表格里编辑，回车跳到下一行同类格；有改动的批次在行尾出现「保存」，保存为整批全量替换，留空的项不会落库。
            </span>
            <span className={AprChromeStyles.legend}>
              <span className={AprChromeStyles.legendDirty}>未保存</span>
              <span className={AprChromeStyles.legendOos}>超标准</span>
              <span className={AprChromeStyles.legendOot}>超趋势</span>
            </span>
          </>
        }
      >
        <Table<EntryRow>
          rowKey={(r) => `${r.batchId}-${r.rowSeq}`}
          className={AprChromeStyles.matrix}
          size="small"
          columns={columns}
          dataSource={visibleRows}
          loading={summaryQuery.isLoading || sectionsQuery.isLoading}
          tableLayout="fixed"
          scroll={{ x: scrollX }}
          pagination={false}
          rowClassName={(r) =>
            multiRow && firstRowSeqOfBatch.get(r.batchId) === r.rowSeq
              ? AprChromeStyles.batchStart
              : ''
          }
          locale={{
            emptyText: !activeSectionId ? (
              <EmptyState
                title="先选产品与模板段"
                hint="批次按模板段归档；选好段之后这里会列出该年度的批号。"
              />
            ) : items.length === 0 ? (
              <EmptyState
                title="这个段还没有列定义"
                hint="先到「模板配置」里给这个段添加质量属性与标准限度，录入矩阵会按列定义生成。"
              />
            ) : entryRows.length > 0 && keywordText ? (
              <EmptyState
                title={`没有匹配「${keyword.trim()}」的批号`}
                hint="换个关键词，或清除筛选查看该年度全部批次。"
                action={
                  <Button
                    onClick={() => {
                      setKeyword('')
                      syncUrl({ keyword: null })
                    }}
                  >
                    清除筛选
                  </Button>
                }
              />
            ) : (
              <EmptyState
                title={`${year} 年度还没有登记批次`}
                hint={canEnter ? '点右上角「登记批次」把这本回顾册的第一批批号录进来。' : '本年度还没有登记批次。'}
                action={
                  canEnter && !locked ? (
                    <Button type="primary" onClick={() => setRegisterOpen(true)}>
                      登记批次
                    </Button>
                  ) : undefined
                }
              />
            ),
          }}
        />
      </AprSheet>

      <Modal
        title={`登记批次${currentSection ? `：${currentSection.name}` : ''}`}
        open={registerOpen}
        onOk={handleRegister}
        onCancel={() => setRegisterOpen(false)}
        confirmLoading={registerSaving}
        mask={{ closable: false }}
        destroyOnHidden
      >
        <Form form={registerForm} layout="vertical" initialValues={{ year }}>
          <Form.Item
            name="batch_no"
            label="批号"
            rules={[{ required: true, whitespace: true, message: '请输入批号' }]}
          >
            <Input autoFocus placeholder="如 DT2402001 / KA-ET-2017-001" maxLength={64} />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Form.Item name="year" label="年度" rules={[{ required: true }]}>
              <InputNumber min={2000} max={2100} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="seq"
              label="排序号（可选）"
              tooltip="只影响列表与导出的先后顺序，不显示在「序号」列；留空则按登记时间排在有排序号的批次之后"
            >
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
