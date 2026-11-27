'use client'

import { Fragment, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type {
  CoaTemplateGridBlock,
  CoaTemplateGridCell,
  CoaTemplateGridPara,
  CoaTemplateGridRow,
  CoaTemplateGridSection,
  CoaTemplateSlot,
} from '@/types/qa'
import type { GridIndex } from './coaTemplateBindingModel'
import styles from './CoaTemplateBindingDrawer.module.css'

export interface BoundSlot {
  field: string
  /** 字段的中文名：空结果格里用它标出「这里会写入什么」 */
  label: string
  slot: CoaTemplateSlot
}

export interface CoaTemplateGridPreviewProps {
  grid: CoaTemplateGridSection[]
  index: GridIndex
  /** 已标注的数据位：地址 → 标注 */
  bound: Map<string, BoundSlot>
  /** 已确认「保持模板原文」的数据位 */
  staticSids: Set<string>
  /** 结果列里待处理的格子 */
  residueSids: Set<string>
  /** 核对清单里正在看的字段：它的位置在预览里高亮 */
  focusField: string | null
  /** 正在为这个字段挑位置（null=不在挑）：预览里的段落变成可点 */
  pickingField: string | null
  /** 挑位置时的字段名，拼进按钮的可访问名称 */
  pickingLabel: string
  /** 要滚到视野里的数据位（点清单上的位置时变化）；tick 让同一个位置可以重复定位 */
  locate: { sid: string; tick: number } | null
  onPick: (sid: string) => void
}

type TableBlock = Extract<CoaTemplateGridBlock, { type: 'table' }>

interface PickMode {
  label: string
  onPick: (sid: string) => void
}

/** 段落里的文字：换行照原样显示，空行占位一个不换行空格。 */
function paragraphBody(text: string): ReactNode {
  return text
    ? text.split('\n').map((line, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {line || '\u00a0'}
        </Fragment>
      ))
    : null
}

/** 段落在模板里的对齐方式 → 样式类（结果列的值大多是居中的，预览照原样排）。 */
function alignClassOf(align: string | undefined): string {
  if (align === 'center') return styles.paraCenter
  if (align === 'end') return styles.paraEnd
  if (align === 'justify') return styles.paraJustify
  return ''
}

/** 一个段落：平时是文字；挑位置时是按钮（键盘可达，空段落也要点得到）。 */
function Para({
  sid,
  text,
  context,
  markClass,
  label,
  inplaceSample,
  alignClass,
  full,
  pick,
}: {
  sid: string
  text: string
  context: string
  /** 数据位的高亮（已标注 / 保持原文 / 待处理），非数据位为空串 */
  markClass: string
  /** 已标注数据位的字段名（空格占位和悬停提示用）；非数据位为 null */
  label: string | null
  /** 原位替换时要被替换的那段原文；整格替换为 null */
  inplaceSample: string | null
  alignClass: string
  /** 完整显示，不按行数截断 */
  full: boolean
  pick: PickMode | null
}) {
  // 原位替换：值夹在固定文字中间（标题行流水号），只高亮要被替换的那一段
  const cut =
    inplaceSample && inplaceSample !== text && text.includes(inplaceSample)
      ? text.indexOf(inplaceSample)
      : -1
  const content: ReactNode = !text.trim() && label !== null
    ? // 空白模板的结果格没有文字：用字段名占位，标出「这里会写入什么」
      (
        <span className={`${styles.para} ${markClass} ${styles.paraEmpty}`}>{label}</span>
      )
    : cut >= 0 && inplaceSample ? (
        <>
          {paragraphBody(text.slice(0, cut))}
          <span className={`${styles.para} ${markClass}`}>
            {paragraphBody(inplaceSample)}
          </span>
          {paragraphBody(text.slice(cut + inplaceSample.length))}
        </>
      )
    : markClass ? (
        <span className={`${styles.para} ${markClass}`} title={label ? `将写入：${label}` : undefined}>
          {paragraphBody(text)}
        </span>
      ) : (
        paragraphBody(text)
      )
  const boxClass = `${styles.paraBox} ${full || cut >= 0 ? styles.paraBoxFull : ''} ${alignClass}`

  if (!pick) {
    return (
      <span data-sid={sid} className={boxClass}>
        {content}
      </span>
    )
  }
  // 按钮的可访问名称带上所在行：空结果格看起来一模一样，靠名称区分是哪一行
  const name = `${pick.label}：${text.trim() ? `位置「${text.trim()}」` : '空位置'}（${context}）`
  return (
    <button
      type="button"
      data-sid={sid}
      className={`${styles.pickBtn} ${alignClass}`}
      aria-label={name}
      onClick={() => pick.onPick(sid)}
    >
      {content ?? <span className={styles.pickEmpty}>空</span>}
    </button>
  )
}

/** 纵向合并：起点格要跨过下面连续的续格。 */
function rowSpanOf(rows: CoaTemplateGridRow[], rowIndex: number, cell: CoaTemplateGridCell): number {
  if (cell.vmerge !== 'restart') return 1
  let span = 1
  for (let i = rowIndex + 1; i < rows.length; i += 1) {
    const below = rows[i].cells.find((other) => other.col === cell.col)
    if (below?.vmerge !== 'cont') break
    span += 1
  }
  return span
}

/** 旧式横向合并（不带 gridSpan）：起点格要跨过右边连续的续格。 */
function colSpanOf(cells: CoaTemplateGridCell[], index: number, cell: CoaTemplateGridCell): number {
  let span = cell.span
  if (cell.hmerge === 'restart') {
    for (let i = index + 1; i < cells.length && cells[i].hmerge === 'cont'; i += 1) {
      span += cells[i].span
    }
  }
  return span
}

/** 各网格列宽度 → 百分比。文件里没写列宽（或个别列写坏）时，缺的按最窄的一列补。 */
function columnPercents(block: TableBlock): number[] | null {
  const widths = block.col_widths ?? []
  if (widths.length === 0) return null
  const narrowest = Math.min(...widths)
  const cols = Array.from(
    { length: Math.max(block.ncols, widths.length) },
    (_, i) => widths[i] ?? narrowest
  )
  const total = cols.reduce((sum, width) => sum + width, 0)
  return cols.map((width) => (width / total) * 100)
}

export function CoaTemplateGridPreview({
  grid,
  index,
  bound,
  staticSids,
  residueSids,
  focusField,
  pickingField,
  pickingLabel,
  locate,
  onPick,
}: CoaTemplateGridPreviewProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // 点清单上的位置：把这个数据位滚到预览视野中间。只在明确点击时滚，悬停/聚焦不滚
  useEffect(() => {
    if (!locate) return
    const target = [...(scrollRef.current?.querySelectorAll<HTMLElement>('[data-sid]') ?? [])].find(
      (element) => element.dataset.sid === locate.sid
    )
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    target?.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' })
  }, [locate])

  const stateClassOf = (sid: string): string => {
    const classes: string[] = []
    if (bound.has(sid)) classes.push(styles.paraBound)
    if (staticSids.has(sid)) classes.push(styles.paraStatic)
    if (residueSids.has(sid)) classes.push(styles.paraResidue)
    if (bound.get(sid)?.field === focusField) classes.push(styles.paraFocus)
    return classes.join(' ')
  }
  // 数据位（已标注/保持原文/待处理）都是要核对的内容：完整显示，不截断
  const isMarked = (sid: string) => bound.has(sid) || staticSids.has(sid) || residueSids.has(sid)

  const renderPara = (para: CoaTemplateGridPara) => {
    const owner = bound.get(para.sid)
    return (
      <Para
        key={para.sid}
        sid={para.sid}
        text={index.textOf.get(para.sid) ?? ''}
        context={index.contextOf.get(para.sid) ?? ''}
        markClass={stateClassOf(para.sid)}
        label={owner?.label ?? null}
        inplaceSample={owner?.slot.mode === 'inplace' ? owner.slot.sample : null}
        alignClass={alignClassOf(para.align)}
        full={isMarked(para.sid)}
        pick={pickingField === null ? null : { label: pickingLabel, onPick }}
      />
    )
  }

  const renderCell = (cell: CoaTemplateGridCell): ReactNode => {
    const hasContent =
      pickingField !== null ||
      cell.paras.some(
        (para) => (index.textOf.get(para.sid) ?? '').trim() || isMarked(para.sid)
      )
    // 全空的格子留一行高：表格行的高矮也是文档结构的一部分
    return hasContent ? cell.paras.map((para) => renderPara(para)) : '\u00a0'
  }

  const renderTable = (block: TableBlock) => {
    const percents = columnPercents(block)
    const totalCols = percents?.length ?? 0
    return (
      <table
        key={block.sid}
        className={`${styles.gridTable} ${percents ? styles.gridTableFixed : ''}`}
      >
        {percents && (
          <colgroup>
            {percents.map((percent, i) => (
              <col key={i} style={{ width: `${percent.toFixed(3)}%` }} />
            ))}
          </colgroup>
        )}
        <tbody>
          {block.rows.map((row, rowIndex) => {
            const drawn = row.cells
              .map((cell, cellIndex) => ({ cell, cellIndex }))
              .filter(({ cell }) => cell.vmerge !== 'cont' && cell.hmerge !== 'cont')
            // 续格不画：由合并起点格跨过来
            const used = drawn.reduce(
              (sum, { cell, cellIndex }) => sum + colSpanOf(row.cells, cellIndex, cell),
              0
            )
            // 被上方 rowspan 占住的列也算本行的列：它们有格子，只是由起点格跨过来
            const covered = row.cells
              .filter((cell) => cell.vmerge === 'cont')
              .reduce((sum, cell) => sum + cell.span, 0)
            return (
              <tr key={row.sid}>
                {drawn.map(({ cell, cellIndex }) => (
                  <td
                    key={cell.sid}
                    rowSpan={rowSpanOf(block.rows, rowIndex, cell)}
                    colSpan={colSpanOf(row.cells, cellIndex, cell)}
                  >
                    {renderCell(cell)}
                  </td>
                ))}
                {/* 这一行比网格短（行内格子少）：补一个空格占住剩余的列，列宽才对得上 */}
                {percents && used + covered < totalCols && (
                  <td colSpan={totalCols - used - covered} aria-hidden="true">
                    {'\u00a0'}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    )
  }

  const renderBlocks = (blocks: CoaTemplateGridBlock[]): ReactNode =>
    blocks.map((block) => {
      if (block.type === 'p') {
        const text = index.textOf.get(block.sid) ?? ''
        // 空段落不是数据位候选（挑位置时除外，那时它是可点的空位）
        if (!text.trim() && !isMarked(block.sid) && pickingField === null) return null
        return (
          <p key={block.sid} className={styles.docLine}>
            {renderPara(block)}
          </p>
        )
      }
      if (block.type === 'textbox') {
        return (
          <div key={block.sid} className={styles.textbox}>
            <div className={styles.sectionTitle}>文本框</div>
            {renderBlocks(block.blocks)}
          </div>
        )
      }
      return renderTable(block)
    })

  return (
    <div tabIndex={0} role="region" aria-label="模板内容预览" className={styles.gridScroll} ref={scrollRef}>
      <div className={styles.paper}>
        {grid.map((section) => (
          <div key={`${section.part}-${section.sid ?? ''}`}>
            {grid.length > 1 && <div className={styles.sectionTitle}>{section.title}</div>}
            {renderBlocks(section.blocks)}
          </div>
        ))}
      </div>
    </div>
  )
}
