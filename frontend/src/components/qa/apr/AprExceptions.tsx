'use client'

import { Button } from 'antd'
import { AprChromeStyles, AprStamp } from './AprChrome'
import type { AprSummary } from '@/types/qa'

export type ExceptionKind = 'oos' | 'oot'

/** 结论条里直接列出的越界项上限，超出部分指向下方各段明细。 */
const MAX_EXCEPTION_ROWS = 12

export interface AprException {
  key: string
  sectionId: string
  sectionName: string
  batchId: string
  batchNo: string
  rowSeq: number
  rowLabel: string | null
  itemId: string
  itemName: string
  value: string
  unit: string | null
  status: ExceptionKind
}

/** 汇总全部段里 status 非 normal 的格子；超标排在预警前面（先看最严重的）。 */
export function collectExceptions(summary: AprSummary | null): AprException[] {
  if (!summary) return []
  const list: AprException[] = []
  for (const section of summary.sections) {
    for (const row of section.rows) {
      for (const item of section.items) {
        const cell = row.cells[item.id]
        if (!cell || (cell.status !== 'oos' && cell.status !== 'oot')) continue
        list.push({
          key: `${section.id}-${row.batch_id}-${row.row_seq}-${item.id}`,
          sectionId: section.id,
          sectionName: section.name,
          batchId: row.batch_id,
          batchNo: row.batch_no,
          rowSeq: row.row_seq,
          rowLabel: section.multi_row ? row.row_label || `第 ${row.row_seq} 行` : null,
          itemId: item.id,
          itemName: `${item.name_cn}${item.code.endsWith('#min') ? ' MIN' : item.code.endsWith('#max') ? ' MAX' : ''}`,
          value: String(cell.num ?? cell.text ?? ''),
          unit: item.unit,
          status: cell.status,
        })
      }
    }
  }
  return list.sort((a, b) => (a.status === b.status ? 0 : a.status === 'oos' ? -1 : 1))
}

/** 年度结论条：OOS/OOT 计数 + 越界清单（点击定位到具体格子）+ 必填完整性提示。 */
export function AprExceptions({
  exceptions,
  rowCount,
  missingCount,
  fixHref,
  onJump,
  flush = false,
}: {
  exceptions: AprException[]
  rowCount: number
  missingCount: number
  fixHref: string | null
  onJump: (exception: AprException) => void
  flush?: boolean
}) {
  const oos = exceptions.filter((e) => e.status === 'oos').length
  const oot = exceptions.length - oos
  const box = flush
    ? `${AprChromeStyles.exceptions} ${AprChromeStyles.exceptionsFlush}`
    : AprChromeStyles.exceptions

  if (exceptions.length === 0) {
    return (
      <div className={box}>
        {missingCount > 0 ? (
          <div className={AprChromeStyles.conclusion}>
            <AprStamp tone="warn">待补全</AprStamp>
            <p className={AprChromeStyles.conclusionText}>
              本年度 {rowCount} 行批值未发现 OOS 超标或 OOT 预警，但还有 {missingCount}{' '}
              个必填格未填写；补齐后再定稿更稳妥。
            </p>
            {fixHref && (
              <Button size="small" href={fixHref}>
                去数据录入
              </Button>
            )}
          </div>
        ) : (
          <div className={AprChromeStyles.conclusion}>
            <span className={AprChromeStyles.conclusionCheck} aria-hidden="true">
              ✓
            </span>
            <p className={AprChromeStyles.conclusionText}>
              本年度 {rowCount} 行批值未发现 OOS 超标或 OOT 预警，可以直接定稿。
            </p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={box}>
      <div className={AprChromeStyles.exceptionsHead}>
        <span className={AprChromeStyles.count}>
          <span className={`${AprChromeStyles.countValue} ${AprChromeStyles.countValueOos}`}>{oos}</span>
          <span className={AprChromeStyles.countLabel}>OOS 超标</span>
        </span>
        <span className={AprChromeStyles.count}>
          <span className={`${AprChromeStyles.countValue} ${AprChromeStyles.countValueOot}`}>{oot}</span>
          <span className={AprChromeStyles.countLabel}>OOT 预警</span>
        </span>
        <span className={AprChromeStyles.exceptionsNote}>点一行定位到越界单元格</span>
      </div>
      <div className={AprChromeStyles.exceptionsList}>
        {exceptions.slice(0, MAX_EXCEPTION_ROWS).map((exception) => (
          <button
            key={exception.key}
            type="button"
            className={AprChromeStyles.exceptionRow}
            onClick={() => onJump(exception)}
          >
            <span className={AprChromeStyles.exceptionSection} title={exception.sectionName}>
              {exception.sectionName}
            </span>
            <span className={AprChromeStyles.batchNo}>
              {exception.batchNo}
              {exception.rowLabel ? ` ${exception.rowLabel}` : ''}
            </span>
            <span
              style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={exception.itemName}
            >
              {exception.itemName}
            </span>
            <span className={AprChromeStyles.exceptionValue}>
              {exception.value}
              {exception.unit ? <span className={AprChromeStyles.unit}>{exception.unit}</span> : null}
            </span>
            <AprStamp tone={exception.status === 'oos' ? 'locked' : 'warn'}>
              {exception.status === 'oos' ? '超标' : '预警'}
            </AprStamp>
          </button>
        ))}
        {exceptions.length > MAX_EXCEPTION_ROWS && (
          <div className={AprChromeStyles.exceptionsMore}>
            另有 {exceptions.length - MAX_EXCEPTION_ROWS} 项越界，见下方各段明细（越界单元格带语义色）。
          </div>
        )}
        {missingCount > 0 && (
          <div className={AprChromeStyles.exceptionsMore}>
            另有 {missingCount} 个必填格未填写，补齐后再定稿更稳妥。
            {fixHref && (
              <Button type="link" size="small" href={fixHref} style={{ paddingInline: 4 }}>
                去数据录入
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
