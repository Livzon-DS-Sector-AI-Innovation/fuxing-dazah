'use client'

import { useEffect, useRef, useState } from 'react'
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
  Segmented,
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
import { createAprBatch, deleteAprBatch, saveAprBatchValues } from '@/actions/qa'
import { fetchAprProducts, fetchAprSections, fetchAprSummary } from '@/lib/api/qa'
import type { AprItem } from '@/types/qa'
import {
  AprChromeStyles,
  AprMeta,
  AprScopeBar,
  AprSheet,
  AprStamp,
  AprYearField,
  prefersReducedMotion,
} from './AprChrome'
import { confirmAsync, DANGER_OK_PROPS, DATA_KIND_LABEL } from './AprConfigShared'
import { AprEntryCell } from './AprEntryCell'
import {
  draftChangeCount,
  draftKeyOf,
  draftTimestamp,
  EntryDraftBanner,
  pruneDraft,
  removeDraft,
  writeDraft,
  type EntryDraft,
} from './AprEntryDraft'
import {
  buildEntryRows,
  cellFilled,
  cellStatus,
  cellTextInvalid,
  focusRowSibling,
  itemDisplayName,
  omitByPrefix,
  reverseByBatch,
  stripRowEdits,
  type EditKey,
  type EntryRow,
  type GridValue,
} from './AprEntryShared'
import { AprImportModal } from './AprImportModal'

// 纯函数（格子解析/校验、矩阵行构建、草稿读写）拆在 AprEntryShared / AprEntryDraft，
// 可编辑格渲染在 AprEntryCell；本文件只保留页面状态与保存流程。

// ═════════════════════════ 数据录入页 ═════════════════════════

export function AprEntryPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const router = useRouter()
  const { hasPermission } = usePermission()
  // 写按钮按 enter 码显隐：只读用户看不到登记/保存/删除，不必靠后端 403 兜底
  const canEnter = hasPermission('qa:apr:enter')
  const searchParams = useSearchParams()
  // 选择状态同步进 URL（?product=&section=&year=&keyword=），刷新/分享链接都能恢复现场。
  // product/section 在 URL 里用直观字符不用 UUID：product=产品代码（全局唯一）、
  // section=模板段名称（产品内唯一）；ID 只在内存流转，写 URL 时反查 code/name。
  // URL 参数不能在首帧同步解析成 ID（列表是异步加载的，useEffect 镜像 state 又被
  // eslint 禁），所以选择拆成两层：picked* 存显式切换的 ID，URL 字符在渲染时解析。
  const productParam = searchParams.get('product')
  const sectionParam = searchParams.get('section')
  const [pickedProductId, setPickedProductId] = useState<string | null>(null)
  const [pickedSectionId, setPickedSectionId] = useState<string | null>(null)
  const [year, setYear] = useState<number>(() => {
    const raw = Number(searchParams.get('year'))
    return Number.isInteger(raw) && raw >= 2000 && raw <= 2100 ? raw : new Date().getFullYear()
  })
  const [keyword, setKeyword] = useState(() => searchParams.get('keyword') ?? '')
  // 降序显示（?desc=1）：新批次排最前，录入最新数据免滚到底部；只影响展示顺序，
  // 不清行内编辑（格子键与顺序无关），所以切排序不走 guardDirty。
  const [desc, setDesc] = useState(() => searchParams.get('desc') === '1')

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
  const [flashKey, setFlashKey] = useState<EditKey | null>(null)
  const [saveProgress, setSaveProgress] = useState<{ done: number; total: number } | null>(null)
  const latestDraft = useRef<{ key: string; draft: EntryDraft } | null>(null)
  const flashTimer = useRef<number | null>(null)

  const [registerOpen, setRegisterOpen] = useState(false)
  const [registerSaving, setRegisterSaving] = useState(false)
  const [registerForm] = Form.useForm()
  const [importOpen, setImportOpen] = useState(false)

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
  // 进页默认选中：显式切换 > URL 产品代码解析（产品已删/字符不存在则视为无效）>
  // 第一个启用产品；派生而非 state，不写回 URL，用户显式切换时才同步链接。
  const pickedProduct = products.some((p) => p.id === pickedProductId) ? pickedProductId : null
  const urlProduct = productParam
    ? products.find((p) => p.code === productParam) ?? null
    : null
  const activeProductId =
    pickedProduct ?? urlProduct?.id ?? (products.length > 0 ? products[0].id : null)

  const sectionsQuery = useQuery({
    queryKey: ['qa', 'apr', 'sections', activeProductId],
    queryFn: () => fetchAprSections(activeProductId!),
    enabled: !!activeProductId,
  })
  const sections = sectionsQuery.data ?? []
  // 段名在产品内唯一（uq_qa_apr_sections_product_name），可直接当 URL 标识解析
  const pickedSection = sections.some((s) => s.id === pickedSectionId) ? pickedSectionId : null
  const urlSection = sectionParam
    ? sections.find((s) => s.name === sectionParam) ?? null
    : null
  const activeSectionId =
    pickedSection ?? urlSection?.id ?? (sections.length > 0 ? sections[0].id : null)
  const currentSection = sections.find((s) => s.id === activeSectionId) ?? null

  // 草稿按「产品 × 段 × 年度」分键：切换上下文后仍能回到各自的未保存现场。
  const draftKey =
    activeProductId && activeSectionId ? draftKeyOf(activeProductId, activeSectionId, year) : null

  /** 丢弃当前上下文的草稿（保存成功、还原或确认放弃后调用）。 */
  const discardDraft = () => {
    latestDraft.current = null
    if (draftKey) removeDraft(draftKey)
  }

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
  // summary 只携带已登记批次的段：列已配好但该年度还没有批次时段不在 payload 里，
  // 空态要靠 sections 接口的列定义区分「没列」和「没批次」，别误报没列。
  const sectionHasActiveItems = currentSection?.items?.some((i) => i.is_active) ?? false

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'summary'] })
    void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'trend'] })
  }

  // 矩阵行构建抽成组件外纯函数；派生值直接计算，由 React Compiler 自动记忆化
  // （手写 useMemo 会被其判为「依赖可能被变异」而 bail out 报错）
  const entryRows = buildEntryRows(sectionPayload?.rows, extraRows)

  const keywordText = keyword.trim().toLowerCase()
  const orderedRows = desc ? reverseByBatch(entryRows) : entryRows
  const visibleRows = keywordText
    ? orderedRows.filter((r) => r.batchNo.toLowerCase().includes(keywordText))
    : orderedRows
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

  // 行内编辑只存在内存里：按 250ms 防抖写 localStorage，覆盖刷新、崩溃与站内跳转；
  // 保存、还原或确认放弃后由对应操作清除。
  useEffect(() => {
    if (!hasDirty) {
      // 行级还原/删掉最后一条加行等路径没有显式 discard，靠这里清掉已写过盘的草稿；
      // 首屏挂载时 latestDraft 为空，不会误删上次会话留下的待恢复草稿。
      const latest = latestDraft.current
      if (latest) removeDraft(latest.key)
      latestDraft.current = null
      return
    }
    if (!draftKey) return
    const draft: EntryDraft = {
      v: 1,
      edits,
      labelEdits,
      extraRows,
      removedRows: [...removedRows],
      savedAt: draftTimestamp(),
    }
    latestDraft.current = { key: draftKey, draft }
    const timer = window.setTimeout(() => writeDraft(draftKey, draft), 250)
    return () => window.clearTimeout(timer)
  }, [draftKey, hasDirty, edits, labelEdits, extraRows, removedRows])

  // 组件卸载（站内跳转/关标签页）时同步落盘，避免防抖计时器被 cleanup 取消而丢最后一次输入。
  useEffect(
    () => () => {
      const latest = latestDraft.current
      if (latest) writeDraft(latest.key, latest.draft)
    },
    [],
  )

  // 刷新/关标签页会丢行内编辑：落盘草稿后再交给浏览器原生确认兜底
  useEffect(() => {
    if (!hasDirty) return
    const warn = (event: BeforeUnloadEvent) => {
      const latest = latestDraft.current
      if (latest) writeDraft(latest.key, latest.draft)
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [hasDirty])

  /** 切换产品/段/年度、导入前先对未保存改动做一次确认；确认即丢弃当前草稿。 */
  const guardDirty = (
    action: () => void,
    options?: { title?: string; content?: string; okText?: string; cancelText?: string },
  ) => {
    if (dirtyBatches.size === 0) {
      action()
      return
    }
    confirmAsync(modal, {
      title: options?.title ?? '放弃未保存的改动？',
      content:
        options?.content ??
        `${dirtyBatches.size} 个批次还有未保存的改动，切换后这些改动会丢失。`,
      okText: options?.okText ?? '放弃并切换',
      cancelText: options?.cancelText ?? '留在本页',
      okButtonProps: DANGER_OK_PROPS,
      onOk: () => {
        discardDraft()
        action()
      },
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
    setFlashKey(null)
  }

  /** 恢复 localStorage 草稿；只保留当前还存在的批次，避免幽灵未保存计数。 */
  const restoreDraft = (draft: EntryDraft) => {
    const batchIds = new Set(entryRows.map((row) => row.batchId))
    const pruned = pruneDraft(draft, batchIds)
    setEdits(pruned.edits)
    setLabelEdits(pruned.labelEdits)
    setExtraRows(pruned.extraRows)
    setRemovedRows(new Set(pruned.removedRows))
    setCellErrors({})
    setFocusedKey(null)
    message.success(`已恢复 ${draftChangeCount(pruned)} 处未保存修改，请检查后保存`)
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

  const setCellError = (key: EditKey, message: string | null) => {
    setCellErrors((prev) => {
      if (message == null) {
        if (!prev[key]) return prev
        const next = { ...prev }
        delete next[key]
        return next
      }
      return { ...prev, [key]: message }
    })
  }

  const invalidTextMessage = (item: AprItem) =>
    item.quick_values.length > 0
      ? `只能填数字或：${item.quick_values.join('、')}`
      : '只能填数字（该列未配置文字结果）'

  /** 数值列文字结果在离开格子时校验，避免边打字边报红（如「未检出」打到一半）。 */
  const validateNumericCell = (key: EditKey, item: AprItem, cell: GridValue) => {
    if (item.value_type !== 'number') return
    setCellError(key, cellTextInvalid(item, cell) ? invalidTextMessage(item) : null)
  }

  /** 保存失败后定位并高亮第一个错误格；若被批号筛选挡住，先清筛选。 */
  const focusEntryCell = (key: EditKey) => {
    const batchId = key.split('|')[0]
    const batchNo = entryRows.find((row) => row.batchId === batchId)?.batchNo
    if (batchNo && keywordText && !batchNo.toLowerCase().includes(keywordText)) {
      setKeyword('')
      syncUrl({ keyword: null })
    }
    setFlashKey(key)
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => {
      setFlashKey((current) => (current === key ? null : current))
    }, 1600)
    // 等可能的「清除筛选」渲染完成后再定位
    window.setTimeout(() => {
      const td = document.getElementById(`apr-entry-cell-${key}`)
      const input = td?.querySelector('input')
      td?.scrollIntoView({
        block: 'center',
        inline: 'center',
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      })
      input?.focus({ preventScroll: true })
    }, 60)
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
      focusEntryCell(Object.keys(errors)[0])
      return false
    }
    // 数值列文字结果必须命中该列快捷值白名单（后端保存时同口径兜底）
    const invalidErrors: Record<EditKey, string> = {}
    for (const row of batchRows) {
      for (const item of items) {
        if (item.value_type !== 'number') continue
        if (!cellTextInvalid(item, cellOf(row, item))) continue
        invalidErrors[`${batchId}|${item.id}|${row.rowSeq}`] = invalidTextMessage(item)
      }
    }
    if (Object.keys(invalidErrors).length > 0) {
      setCellErrors((prev) => ({ ...prev, ...invalidErrors }))
      message.error(`${batchNo} 有 ${Object.keys(invalidErrors).length} 处文字结果不在该列允许范围内`)
      focusEntryCell(Object.keys(invalidErrors)[0])
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
      // 这一批是最后一个脏批次时，草稿已无用，直接清掉
      if (dirtyBatches.size === 1 && dirtyBatches.has(batchId)) discardDraft()
      invalidate()
      return true
    } catch (error) {
      // 服务端 action 本身抛错（网络中断/代理超时）时不能让调用方误判为已保存
      message.error(error instanceof Error ? error.message : '保存失败，请检查网络后重试')
      return false
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
    setSaveProgress({ done: 0, total: targets.length })
    let allOk = targets.length > 0
    try {
      for (const [index, target] of targets.entries()) {
        if (!(await saveBatch(target.id, target.no))) {
          allOk = false
          break
        }
        setSaveProgress({ done: index + 1, total: targets.length })
      }
    } finally {
      setAllSaving(false)
      setSaveProgress(null)
      if (allOk) discardDraft()
    }
  }

  const resetAllEdits = () => {
    confirmAsync(modal, {
      title: '放弃未保存的改动？',
      content: `${dirtyBatches.size} 个批次还有未保存的改动，还原后这些改动会丢失。`,
      okText: '放弃并还原',
      cancelText: '继续编辑',
      okButtonProps: DANGER_OK_PROPS,
      onOk: () => {
        discardDraft()
        clearAllEdits()
      },
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
      // 登记到其他年度时切过去，否则新批次不会出现在当前表格里
      if (values.year !== year) {
        if (hasDirty) {
          message.info(
            `批次已登记到 ${values.year} 年度；当前还有未保存改动，保存后再切换查看。`,
          )
        } else {
          setYear(values.year)
          syncUrl({ year: String(values.year) })
        }
      }
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
    const rowDesc = multiRow
      ? `第${row.rowSeq}行${row.rowLabel ? ` ${row.rowLabel}` : ''}`
      : ''
    return (
      <AprEntryCell
        item={item}
        cell={cell}
        status={cellStatus(item, cell, row.server?.cells[item.id]?.status)}
        error={cellErrors[key]}
        removed={removedRows.has(`${row.batchId}|${row.rowSeq}`)}
        readOnly={readOnly}
        focused={focusedKey === key}
        cellLabel={`${row.batchNo}${rowDesc ? ` ${rowDesc}` : ''} ${itemDisplayName(item)}`}
        onCellChange={(patch) => setCell(key, patch)}
        onFocusedChange={(value) => {
          if (value) setFocusedKey(key)
          else setFocusedKey((k) => (k === key ? null : k))
        }}
        onBlurValidate={(value) => validateNumericCell(key, item, value)}
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
    // 有未保存编辑的格子铺淡琥珀底，与操作列「保存」呼应；保存失败时按 id 定位错误格
    onCell: (row) => {
      const key = `${row.batchId}|${item.id}|${row.rowSeq}`
      return {
        id: `apr-entry-cell-${key}`,
        className:
          clsx(
            edits[key] != null && flashKey !== key && AprChromeStyles.cellDirty,
            flashKey === key && AprChromeStyles.cellFlash,
            groupStart && AprChromeStyles.groupStart,
          ) || undefined,
        style: { padding: '4px 8px' },
      }
    },
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
                  aria-label={`${row.batchNo} 第${row.rowSeq}行 行名`}
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
    <div style={hasDirty ? { ...qaPageStyle, paddingBottom: 76 } : qaPageStyle}>
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

      {!hasDirty && draftKey && !summaryQuery.isLoading && entryRows.length > 0 && (
        <EntryDraftBanner
          key={draftKey}
          draftKey={draftKey}
          batchIds={new Set(entryRows.map((row) => row.batchId))}
          onRestore={restoreDraft}
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
              disabled={allSaving}
              onChange={(v) => {
                guardDirty(() => {
                  setPickedProductId(v)
                  setPickedSectionId(null)
                  clearAllEdits()
                  syncUrl({
                    product: products.find((p) => p.id === v)?.code ?? null,
                    section: null,
                  })
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
                  setPickedSectionId(v)
                  clearAllEdits()
                  syncUrl({ section: sections.find((s) => s.id === v)?.name ?? null })
                })
              }}
              disabled={!activeProductId || allSaving}
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
              disabled={allSaving}
              onChange={(v) => {
                guardDirty(() => {
                  setYear(v)
                  clearAllEdits()
                  syncUrl({ year: String(v) })
                })
              }}
            />
            <Tooltip title="降序：排序号新 / 最新登记的批次排最前，录入最新数据不用滚到表格底部">
              <Segmented
                value={desc ? 'desc' : 'asc'}
                onChange={(v) => {
                  const next = v === 'desc'
                  setDesc(next)
                  syncUrl({ desc: next ? '1' : null })
                }}
                options={[
                  { value: 'asc', label: '升序' },
                  { value: 'desc', label: '降序' },
                ]}
              />
            </Tooltip>
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
            {currentSection?.multi_row && <AprStamp tone="warn">一批多行</AprStamp>}
            {locked && <AprStamp tone="locked">年度已定稿</AprStamp>}
            {canEnter && (
              <Button
                disabled={!activeSectionId || locked || allSaving}
                onClick={() =>
                  guardDirty(
                    () => {
                      clearAllEdits()
                      setImportOpen(true)
                    },
                    {
                      title: '导入会先丢弃未保存的改动',
                      content: `${dirtyBatches.size} 个批次还有未保存的改动，导入前会先丢弃这些本地修改（文件里的值不受影响）。`,
                      okText: '丢弃并导入',
                      cancelText: '先保存',
                    },
                  )
                }
              >
                导入 Excel
              </Button>
            )}
            {canEnter && (
              <Button type="primary" disabled={!activeSectionId || locked || allSaving} onClick={() => setRegisterOpen(true)}>
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
            ) : items.length === 0 && !sectionHasActiveItems ? (
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

      <AprImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={invalidate}
        sectionId={activeSectionId}
        sectionName={currentSection?.name ?? null}
        year={year}
      />

      {hasDirty && (
        <div className={AprChromeStyles.saveBar} role="status" aria-live="polite">
          <span className={AprChromeStyles.saveBarCount}>
            {saveProgress
              ? `正在保存 ${saveProgress.done}/${saveProgress.total} 批`
              : `${dirtyBatches.size} 批未保存`}
          </span>
          <Button
            size="small"
            disabled={allSaving || savingBatchId !== null}
            onClick={resetAllEdits}
          >
            还原
          </Button>
          {canEnter && !locked && (
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
        </div>
      )}
    </div>
  )
}
