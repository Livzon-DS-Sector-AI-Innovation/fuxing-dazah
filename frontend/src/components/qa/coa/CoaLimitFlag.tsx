'use client'

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ExclamationCircleFilled } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { limitHitLabel, limitHitStamp, tallyLimitHits } from './coaSpecLimit'
import type { CoaItemLimitHit, CoaLimitHit } from './coaSpecLimit'
import styles from './CoaLimitFlag.module.css'

/** 动画类操作尊重系统「减弱动态效果」设置。 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// ─────────────────────── 输入停手判定 ───────────────────────

/** 停手多久算「输完」。 */
const SETTLE_MS = 450

/**
 * 录入单里正在输入的那个结果格（同一时刻最多一个）。
 *
 * 越界标记等停手 SETTLE_MS 或离开输入框才出：限度 ≥95 时敲到「9」是输入中途，
 * 不该闪一下超标。没聚焦时发生的变化（导入预填、编辑回填）不经过这里，立即判。
 */
export function useSettledInput() {
  const [unsettledId, setUnsettledId] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }

  /** 某格的内容被改了：从这一刻起重新计时。 */
  const markUnsettled = (id: string) => {
    clearTimer()
    setUnsettledId(id)
    timer.current = window.setTimeout(() => {
      timer.current = null
      setUnsettledId((current) => (current === id ? null : current))
    }, SETTLE_MS)
  }

  /** 离开输入框：立即判。 */
  const settle = () => {
    clearTimer()
    setUnsettledId(null)
  }

  // 弹窗在计时途中关掉时撤掉计时器
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  return { unsettledId, markUnsettled, settle }
}

/**
 * 「跳到下一处越界」：按项目顺序循环往下走（水分 → 需氧菌 → 回到第一处），每处都会轮到。
 * 头一次先找可视区外的第一格；都露着就从第一格开始。
 *
 * 不用「每次找可视区外的第一格」：越界格分上下两簇时，跳到下面一簇会让上面那簇
 * 又滚出可视区，下一次又被它顶回去，同簇的第二格永远轮不到。
 */
export function useJumpNextHit() {
  const lastKey = useRef<string | null>(null)
  return (scope: HTMLElement | null) => {
    const flagged = Array.from(scope?.querySelectorAll<HTMLElement>('input[data-coa-limit-hit]') ?? [])
    if (!flagged.length || !scope) return
    const keyOf = (index: number) => flagged[index].dataset.coaResultInput ?? null
    // 焦点正停在某格越界结果上（刚跳过去 / 用户自己点进去的）就从它的下一格走
    const active = document.activeElement
    const anchor =
      active instanceof HTMLElement && active.matches('input[data-coa-limit-hit]')
        ? flagged.indexOf(active)
        : flagged.findIndex((input) => input.dataset.coaResultInput === lastKey.current)
    let index: number
    if (anchor >= 0) {
      index = (anchor + 1) % flagged.length
    } else {
      const box = scope.getBoundingClientRect()
      const firstHidden = flagged.findIndex((input) => {
        const rect = input.getBoundingClientRect()
        return rect.top < box.top || rect.bottom > box.bottom
      })
      index = firstHidden >= 0 ? firstHidden : 0
    }
    lastKey.current = keyOf(index)
    flagged[index].scrollIntoView({
      block: 'center',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    })
    flagged[index].focus({ preventScroll: true })
  }
}

// ─────────────────────── 标记 ───────────────────────

/**
 * 文字标记：底色 + 描边。超标（确定超出）红、可能超限橙——状态由文字道出，不只靠颜色。
 * 套在已经染了同色底、描了同色边的输入框里时用 bare 去掉描边，免得成了双框。
 * 给了 title 就带悬停说明（antd Tooltip 的子节点必须是 DOM 元素，所以包在这里）。
 */
export function CoaLimitMark({
  hit,
  title,
  id,
  bare = false,
  children,
}: {
  hit: CoaLimitHit
  title?: ReactNode
  id?: string
  bare?: boolean
  children: ReactNode
}) {
  const mark = (
    <span
      id={id}
      className={`${styles.mark} ${
        hit.certainty === 'possible' ? styles.markPossible : styles.markOvers
      }${bare ? ` ${styles.markBare}` : ''}`}
    >
      {children}
    </span>
  )
  return title ? <Tooltip title={title}>{mark}</Tooltip> : mark
}

/** 出具记录表的越界格：数值套底色 + 左缘竖条，悬停 / 聚焦看说明。 */
export function CoaLimitPill({
  hit,
  title,
  children,
}: {
  hit: CoaLimitHit
  title?: ReactNode
  children: ReactNode
}) {
  return (
    <Tooltip title={title}>
      <span
        className={`${styles.pill} ${
          hit.certainty === 'possible' ? styles.pillPossible : styles.pillOvers
        }`}
        tabIndex={0}
      >
        {children}
      </span>
    </Tooltip>
  )
}

/** 计数标记的悬停说明里最多列几项。 */
const TIP_MAX = 8

/** 录入单标题行的越界计数：「2 项超标」，点一下跳到下一处。没有越界时不渲染。 */
export function CoaLimitTally({ hits, onJump }: { hits: CoaItemLimitHit[]; onJump: () => void }) {
  const { overs, possible } = tallyLimitHits(hits)
  return (
    // 计数变化（刚敲进一个越界值 / 改回合格）读屏器要能播报
    <span role="status" aria-live="polite">
      <Tooltip
        title={
          <div className={styles.tip}>
            {hits.slice(0, TIP_MAX).map(({ item, hit }) => (
              <div key={item.id} className={styles.tipRow}>
                <span className={styles.tipName}>{item.name_cn}</span>
                <span>{limitHitLabel(hit)}</span>
              </div>
            ))}
            {hits.length > TIP_MAX && (
              <div className={styles.tipMore}>另有 {hits.length - TIP_MAX} 项</div>
            )}
          </div>
        }
      >
        <button
          type="button"
          className={`${styles.tally} ${overs > 0 ? styles.tallyOvers : styles.tallyPossible}`}
          onClick={onJump}
        >
          <ExclamationCircleFilled />
          <span>
            {overs > 0 && `${overs} 项超标`}
            {overs > 0 && possible > 0 && '、'}
            {possible > 0 && `${possible} 项可能超限`}
          </span>
        </button>
      </Tooltip>
    </span>
  )
}

// ─────────────────────── 清单 ───────────────────────

export interface CoaLimitListRow {
  key: string
  batchNo: string
  detail: CoaItemLimitHit
}

/** 越界清单：一行一项（批号 / 项目 / 结果 / 标记），点一行定位到单元格。 */
export function CoaLimitList({
  rows,
  onPick,
}: {
  rows: CoaLimitListRow[]
  onPick: (row: CoaLimitListRow) => void
}) {
  return (
    <div className={styles.list}>
      {rows.map((row) => (
        <button
          key={row.key}
          type="button"
          className={styles.row}
          onClick={() => onPick(row)}
        >
          <span className={styles.rowBatch}>{row.batchNo}</span>
          <span className={styles.rowItem}>{row.detail.item.name_cn}</span>
          <span className={styles.rowValue}>{row.detail.hit.display}</span>
          <CoaLimitMark hit={row.detail.hit}>{limitHitStamp(row.detail.hit)}</CoaLimitMark>
        </button>
      ))}
    </div>
  )
}
