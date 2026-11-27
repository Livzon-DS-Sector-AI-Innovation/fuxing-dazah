'use client'

import type { CSSProperties, ReactNode } from 'react'
import { InputNumber } from 'antd'
import clsx from 'clsx'
import styles from './AprChrome.module.css'

/**
 * 年度产品回顾（PQR）三个页面共用的版面语言。
 *
 * 版式思路来自这本「年度回顾册」本身：批号在左、质量属性在右、限度写在列头、
 * 年末定稿盖戳。所以三个页面共用同一条册条（范围 + 状态 + 主操作）与同一种
 * sheet（一页记录），结构本身编码信息，不再额外加装饰。
 */

// ── 册条 ─────────────────────────────────────────────────────────────

export function AprScopeBar({
  lead,
  children,
  tail,
}: {
  lead?: ReactNode
  children?: ReactNode
  tail?: ReactNode
}) {
  return (
    <div className={styles.scopeBar}>
      {(lead || children) && (
        <div className={styles.scopeCluster}>
          {lead}
          {children}
        </div>
      )}
      {tail && <div className={styles.scopeTail}>{tail}</div>}
    </div>
  )
}

/** 同类事实之间用 1px 竖线分隔，替代「A · B · C」这种元串。 */
export function AprMeta({ items }: { items: (ReactNode | false | null | undefined)[] }) {
  const visible = items.filter(Boolean) as ReactNode[]
  if (visible.length === 0) return null
  return (
    <div className={styles.meta}>
      {visible.map((item, index) => (
        <span key={index} className={styles.metaItem}>
          {item}
        </span>
      ))}
    </div>
  )
}

// ── 状态戳 ───────────────────────────────────────────────────────────

const STAMP_CLASS = {
  locked: styles.stampLocked,
  open: styles.stampOpen,
  warn: styles.stampWarn,
  neutral: styles.stampNeutral,
} as const

export type AprStampTone = keyof typeof STAMP_CLASS

/** 年度状态用「盖章」的语言表达：纸面上确定过的结论，不是可点的标签。 */
export function AprStamp({
  tone = 'neutral',
  icon,
  children,
}: {
  tone?: AprStampTone
  icon?: ReactNode
  children: ReactNode
}) {
  return (
    <span className={clsx(styles.stamp, STAMP_CLASS[tone])}>
      {icon}
      {children}
    </span>
  )
}

// ── 年度 ─────────────────────────────────────────────────────────────

/** 录入页的年度字段：可改，用「年度 2026」的票据形状。 */
export function AprYearField({
  value,
  onChange,
  min = 2000,
  max = 2100,
  disabled = false,
}: {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  disabled?: boolean
}) {
  return (
    <label className={clsx(styles.yearField, disabled && styles.yearFieldDisabled)}>
      <span className={styles.yearFieldLabel}>年度</span>
      <InputNumber
        size="small"
        // 票据自己画边框，内层控件不许再画一层；年度不需要上下微调箭头。
        controls={false}
        variant="borderless"
        min={min}
        max={max}
        value={value}
        aria-label="年度"
        disabled={disabled}
        onChange={(next) => {
          // 清空（null）与非法输入不回调：否则 Number(null)=0 会把年度置 0，
          // 请求被后端 ge=2000 拒掉还把 ?year=0 写进 URL
          if (next == null) return
          const parsed = typeof next === 'number' ? next : Number(next)
          if (Number.isFinite(parsed) && parsed >= min && parsed <= max) onChange(parsed)
        }}
      />
    </label>
  )
}

/** 汇总页的年度页签：年度是这本册的索引，所以用可点的数字页签而不是下拉框。 */
export function AprYearTabs({
  years,
  value,
  onChange,
}: {
  years: number[]
  value: number
  onChange: (year: number) => void
}) {
  return (
    <div className={styles.yearTabs} role="tablist" aria-label="年度">
      {years.map((year) => {
        const active = year === value
        return (
          <button
            key={year}
            type="button"
            role="tab"
            aria-selected={active}
            className={clsx(styles.yearTab, active && styles.yearTabActive)}
            onClick={() => onChange(year)}
          >
            {year}
          </button>
        )
      })}
    </div>
  )
}

// ── 下划线分段 ───────────────────────────────────────────────────────

export function AprSegmented<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T
  options: { value: T; label: ReactNode; count?: number }[]
  onChange: (value: T) => void
  ariaLabel?: string
}) {
  return (
    <div className={styles.segmented} role="group" aria-label={ariaLabel}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            className={clsx(styles.segOption, active && styles.segOptionActive)}
            onClick={() => onChange(option.value)}
          >
            {option.label}
            {option.count != null && <span className={styles.segCount}>{option.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

// ── sheet ────────────────────────────────────────────────────────────

export function AprSheet({
  title,
  meta,
  actions,
  toolbar,
  footer,
  bleed = true,
  className,
  bodyClassName,
  children,
}: {
  title: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  toolbar?: ReactNode
  footer?: ReactNode
  /** 表格类内容需要贴边，正文类内容用 false 留 padding。 */
  bleed?: boolean
  className?: string
  /** 需要内部滚动的面板（如配置页目录）用它接管 body 的布局。 */
  bodyClassName?: string
  children: ReactNode
}) {
  return (
    <section className={clsx(styles.sheet, className)}>
      <header className={styles.sheetHead}>
        <div className={styles.sheetTitleWrap}>
          <h2 className={styles.sheetTitle}>{title}</h2>
          {meta}
        </div>
        {actions && <div className={styles.sheetActions}>{actions}</div>}
      </header>
      {toolbar && <div className={styles.sheetToolbar}>{toolbar}</div>}
      <div className={clsx(bleed ? styles.sheetBodyBleed : styles.sheetBody, bodyClassName)}>
        {children}
      </div>
      {footer && <div className={styles.sheetFoot}>{footer}</div>}
    </section>
  )
}

// ── 数字与越界 ───────────────────────────────────────────────────────

export const numStyle: CSSProperties = { fontVariantNumeric: 'tabular-nums' }

/** 数值单元格：越界值带左缘标记 + 语义色，正常值保持安静。 */
export function AprValue({
  value,
  status,
  unit,
}: {
  value: string | number
  status?: 'normal' | 'oos' | 'oot' | null
  /** 列配置了单位时跟在值后面，提醒录入/查看口径（如 %）。 */
  unit?: string | null
}) {
  const body = (
    <>
      {value}
      {unit ? <span className={styles.unit}>{unit}</span> : null}
    </>
  )
  if (status === 'oos') {
    return <span className={clsx(styles.violation, styles.violationOos)}>{body}</span>
  }
  if (status === 'oot') {
    return <span className={clsx(styles.violation, styles.violationOot)}>{body}</span>
  }
  return <span className={styles.num}>{body}</span>
}

/** 动画类操作尊重系统「减少动态效果」设置；SSR 时按不减少处理。 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

export const AprChromeStyles = styles
