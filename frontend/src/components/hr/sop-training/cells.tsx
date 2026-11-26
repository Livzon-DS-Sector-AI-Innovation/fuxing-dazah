// SOP 培训三页共用的展示件：两行单元格、软色状态标签、R/T 完成时间、筛选芯片。
// 只负责「怎么画」，不取数、不持有业务状态。

import type { ReactNode } from 'react'
import { Tooltip } from 'antd'
import { SOP_CHANGE_TYPE_META, SOP_ENTRY_STATUS_META, SOP_RECORD_STATUS_META } from '@/lib/hr'
import styles from './sop-training.module.css'

type TagMeta = { bg: string; text: string }
type ChangeMeta = TagMeta & { dot: string }

const NEUTRAL_TAG: ChangeMeta = {
  bg: 'var(--color-tint-gray)',
  text: 'var(--color-slate)',
  dot: '#a4a097',
}

interface SoftTagProps {
  meta?: TagMeta
  /** 标签前加同色圆点（行首色条、筛选芯片的色点与它呼应） */
  dot?: boolean
  children: ReactNode
}

/** 胶囊状态标签：过渡色底 + 同色系深字；取不到元数据时退成中性灰 */
export function SoftTag({ meta, dot = false, children }: SoftTagProps) {
  const m = meta ?? NEUTRAL_TAG
  return (
    <span className={styles.tag} style={{ background: m.bg, color: m.text }}>
      {dot && <i className={styles.tagDot} style={{ background: m.text }} />}
      {children}
    </span>
  )
}

export function changeTagMeta(color: string | null | undefined): ChangeMeta {
  return (color && SOP_CHANGE_TYPE_META[color]) || NEUTRAL_TAG
}

/** 登记表进度：后端 status 只有「草稿 / 已提交」两种 */
export function recordStatusTagMeta(status: string | null | undefined): TagMeta & { label: string } {
  return SOP_RECORD_STATUS_META[status ?? ''] ?? SOP_RECORD_STATUS_META['草稿']
}

export function entryStatusTagMeta(status: string | null | undefined): TagMeta {
  return SOP_ENTRY_STATUS_META[status ?? ''] ?? NEUTRAL_TAG
}

/** "2026-01-05" / "2026.01.05" → "01.05"；withYear 时保留年份。其他写法原样返回 */
export function formatCnDate(raw: string | null | undefined, withYear = false): string | null {
  if (!raw) return null
  const parts = raw.replaceAll('-', '.').split('.')
  if (parts.length === 3) return withYear ? parts.join('.') : parts.slice(1).join('.')
  return raw
}

const COMPLETE_RE = /^(\d{4})\.(\d{2})\.(\d{2})(?:\((\d{2}:\d{2})-(\d{2}:\d{2})\))?$/
const RANGE_ONLY_RE = /^\((\d{2}:\d{2})-(\d{2}:\d{2})\)$/

/** 完成时间/课时：后端存 "2026.01.04(13:00-14:00)"，也可能只有日期或只有时段；其他历史写法原样展示 */
export function formatCompleteTime(raw: string | null | undefined, withYear = false): string | null {
  if (!raw) return null
  const full = raw.match(COMPLETE_RE)
  if (full) {
    const date = withYear ? `${full[1]}.${full[2]}.${full[3]}` : `${full[2]}.${full[3]}`
    return full[4] ? `${date} ${full[4]}–${full[5]}` : date
  }
  const rangeOnly = raw.match(RANGE_ONLY_RE)
  if (rangeOnly) return `${rangeOnly[1]}–${rangeOnly[2]}`
  return raw
}

const METHOD_LABEL: Record<string, string> = { R: '填写培训完成时间', T: '填写培训课时' }

/** 培训方式 R / T 的小方标（含义见纸质登记表表头） */
export function MethodBadge({ method }: { method: string | null | undefined }) {
  if (!method) return <span className={styles.placeholder}>—</span>
  return (
    <Tooltip title={`${method}：${METHOD_LABEL[method] ?? ''}`}>
      <span className={styles.method}>{method}</span>
    </Tooltip>
  )
}

interface MethodTimeCellProps {
  method: string | null | undefined
  completeTime: string | null | undefined
  /** 跨年展示（二级表）时保留年份；登记表按年筛选，只显示月.日 */
  withYear?: boolean
  /** 次行补充信息，一般是培训师 */
  footnote?: ReactNode
}

export function MethodTimeCell({ method, completeTime, withYear = false, footnote }: MethodTimeCellProps) {
  const text = formatCompleteTime(completeTime, withYear)
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <MethodBadge method={method} />
        {text ? (
          <span className={`${styles.num} whitespace-nowrap text-[13px]`} title={completeTime ?? undefined}>
            {text}
          </span>
        ) : (
          <span className={styles.placeholder}>{method === 'T' ? '课时未填' : '时间未填'}</span>
        )}
      </div>
      {footnote && <div className={styles.cellSecondary}>{footnote}</div>}
    </div>
  )
}

interface FileCellProps {
  name: ReactNode
  /** 次行：文件编号、生效日期等 */
  meta?: ReactNode
  title?: string
}

/** 两行单元格：主行是名称，次行是补充信息；两行各自超长省略 */
export function FileCell({ name, meta, title }: FileCellProps) {
  return (
    <div className="min-w-0">
      <div className={styles.cellPrimary} title={title}>
        {name}
      </div>
      {meta && <div className={styles.cellSecondary}>{meta}</div>}
    </div>
  )
}

interface DepartmentCellProps {
  departments?: string[] | null
  /** 主办部门，在完整名单里标出来 */
  initiator?: string | null
}

/** 涉及部门：首个部门 + 「+N」，完整名单在 Tooltip 里 */
export function DepartmentCell({ departments, initiator }: DepartmentCellProps) {
  if (!departments?.length) return <span className={styles.placeholder}>—</span>
  const [first, ...rest] = departments
  return (
    <Tooltip
      title={
        <div>
          {departments.map((d) => (
            <div key={d}>
              {d}
              {d === initiator && '（主办）'}
            </div>
          ))}
        </div>
      }
    >
      <div className="flex min-w-0 items-center gap-1">
        <span className={styles.deptChip}>{first}</span>
        {rest.length > 0 && <span className={styles.deptMore}>+{rest.length}</span>}
      </div>
    </Tooltip>
  )
}

interface ChangeTypeFilterProps {
  counts: { name: string; count: number }[]
  value: string | null
  onChange: (next: string | null) => void
}

/** 变更类型筛选芯片：单选、可取消；色点与登记表行首色条同源，兼作图例 */
export function ChangeTypeFilter({ counts, value, onChange }: ChangeTypeFilterProps) {
  return (
    <div className={styles.chipGroup} role="group" aria-label="按变更类型筛选">
      {counts.map(({ name, count }) => {
        const meta = changeTagMeta(name)
        const active = value === name
        return (
          <button
            key={name}
            type="button"
            aria-pressed={active}
            className={styles.chipBtn}
            style={active ? { background: meta.bg, borderColor: meta.text, color: meta.text } : undefined}
            onClick={() => onChange(active ? null : name)}
          >
            <i className={styles.chipDot} style={{ background: meta.dot }} />
            {name}
            <span className={styles.chipCount}>{count}</span>
          </button>
        )
      })}
    </div>
  )
}
