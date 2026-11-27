// 录入矩阵的纯函数与类型：从 AprEntryPage 拆出，无 React 依赖（除事件类型），
// 便于单测与复用（汇总页的 #min/#max 展示口径也来自这里）。

import type { KeyboardEvent } from 'react'
import type { AprItem, AprSummaryRow } from '@/types/qa'

/** #min/#max 成对列的名称后缀展示。 */
export function itemDisplayName(item: AprItem): string {
  if (item.code.endsWith('#min')) return `${item.name_cn} MIN`
  if (item.code.endsWith('#max')) return `${item.name_cn} MAX`
  return item.name_cn
}

/** 数值列只接受纯数字（允许负号、小数点与首尾空格），非法输入返回 null。 */
export function parseNumeric(raw: string): number | null {
  const text = raw.trim()
  if (!text) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/** 数值单元格：raw 是输入框里的原文，num 是解析结果（非法/空则为 null）。 */
export type GridValue = { num: number | null; raw: string; text: string }
/** 编辑键：`${batchId}|${itemId}|${rowSeq}`；行标签键：`${batchId}|${rowSeq}`。 */
export type EditKey = string

/** 数值格输入：先 NFKC 归一化（全角数字、＜、．等纠正为半角），解析成功走数值槽；
 *  其余文本原样保留，保存时按该列 quick_values 白名单拦截。 */
export function numberCellPatch(raw: string): Pick<GridValue, 'num' | 'raw' | 'text'> {
  const normalized = raw.normalize('NFKC')
  const num = parseNumeric(normalized)
  return { num, raw: normalized, text: num == null ? normalized.trim() : '' }
}

/** 数值列文字结果是否合法：空值合法，非空必须命中该列快捷值白名单。 */
export function cellTextInvalid(item: AprItem, cell: GridValue): boolean {
  const text = cell.text.trim()
  return cell.num == null && !!text && !item.quick_values.includes(text)
}

/** 单元格是否已填：数值/文字任一槽有值即算（数值列填未检出也算）。 */
export function cellFilled(cell: GridValue | undefined): boolean {
  return cell?.num != null || !!cell?.text?.trim()
}

/** 前端 OOS/OOT 判定（与后端 classify_point 同口径），行内编辑实时着色用。 */
export function classifyCell(item: AprItem, value: number): 'normal' | 'oot' | 'oos' {
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
export function cellStatus(
  item: AprItem,
  cell: GridValue,
  server: 'normal' | 'oot' | 'oos' | null | undefined,
) {
  if (cell.num != null) return classifyCell(item, cell.num)
  return server ?? null
}

/** 矩阵行：一批一行（multi_row 段按已录行号展开，server 为 null 的是未保存的新增行）。 */
export type EntryRow = {
  batchId: string
  batchNo: string
  rowSeq: number
  rowLabel: string | null
  server: AprSummaryRow | null
  extra: boolean
}

/** 矩阵行 = 汇总行 + 本地加行（新行号创建时锁定，避免删行后重排错位）；
 *  加行插到该批最后一行之后，批次已不在汇总里（被删）的加行自然丢弃。 */
export function buildEntryRows(
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

/** 批次整组倒序：只把批次先后反过来，一批多行时行内仍保持 1→n（加行仍贴在组尾）。 */
export function reverseByBatch(rows: EntryRow[]): EntryRow[] {
  const groups: EntryRow[][] = []
  for (const row of rows) {
    const group = groups[groups.length - 1]
    if (group && group[0].batchId === row.batchId) group.push(row)
    else groups.push([row])
  }
  return groups.reverse().flat()
}

export function omitByPrefix<T>(record: Record<string, T>, prefix: string): Record<string, T> {
  const next: Record<string, T> = {}
  for (const [key, value] of Object.entries(record)) {
    if (!key.startsWith(prefix)) next[key] = value
  }
  return next
}

/** 清掉某批某行的全部单元格编辑（删行/删除批次后防脏键残留）。 */
export function stripRowEdits(
  record: Record<EditKey, GridValue>,
  batchId: string,
  rowSeq: number,
) {
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
export function focusRowSibling(e: KeyboardEvent<HTMLInputElement>, col: string, step: 1 | -1) {
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
