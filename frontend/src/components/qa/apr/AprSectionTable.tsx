'use client'

import { useState } from 'react'
import { Button, Table, Tooltip } from 'antd'
import type { ColumnsType, ColumnType } from 'antd/es/table'
import clsx from 'clsx'
import { LineChartOutlined } from '@ant-design/icons'
import { EmptyState } from '@/components/qa/deviation/shared'
import type { AprItem, AprSummaryRow, AprSummarySection, AprTrendStats } from '@/types/qa'
import { AprChromeStyles, AprValue } from './AprChrome'

/** 汇总表格子里给越界清单跳转用的 DOM id（section + 批号 + 行号 + 指标唯一）。 */
export function cellDomId(sectionId: string, batchId: string, rowSeq: number, itemId: string): string {
  return `apr-cell-${sectionId}-${batchId}-${rowSeq}-${itemId}`
}

/** 长表在表内滚动，表头与列统计始终留在视野里；短表不嵌套滚动。 */
const TABLE_SCROLL_Y = 'max(280px, calc(100vh - 460px))'
const TABLE_INNER_SCROLL_MIN_ROWS = 12

/** 表尾统计行清单（对齐年度回顾工具 qa_year_review 的 22 项）：
 * item=列定义自身限度（标准限），stats=查询时统计量。 */
const STAT_FOOTER_ROWS: { label: string; source: 'item' | 'stats'; key: string }[] = [
  { label: '标准上限(USL)', source: 'item', key: 'spec_max' },
  { label: '标准下限(LSL)', source: 'item', key: 'spec_min' },
  { label: '平均值', source: 'stats', key: 'mean' },
  { label: '最大值', source: 'stats', key: 'max' },
  { label: '最小值', source: 'stats', key: 'min' },
  { label: 'STDEVA', source: 'stats', key: 'stdev' },
  { label: '+3σ', source: 'stats', key: 'plus3s' },
  { label: '-3σ', source: 'stats', key: 'minus3s' },
  { label: '+4σ', source: 'stats', key: 'plus4s' },
  { label: '-4σ', source: 'stats', key: 'minus4s' },
  { label: '规格公差(T)', source: 'stats', key: 'tolerance' },
  { label: '规格中心值(U)', source: 'stats', key: 'spec_center' },
  { label: '制程准确度(ca)', source: 'stats', key: 'ca' },
  { label: '制程精密度(cp)', source: 'stats', key: 'cp' },
  { label: '制程能力(CPKu)', source: 'stats', key: 'cpku' },
  { label: '制程能力(CPKl)', source: 'stats', key: 'cpkl' },
  { label: '制程能力(CPK)', source: 'stats', key: 'cpk' },
  { label: 'CPK级别', source: 'stats', key: 'cpk_level' },
  { label: '警告限上限', source: 'stats', key: 'warn_max' },
  { label: '警告限下限', source: 'stats', key: 'warn_min' },
  { label: '行动限上限', source: 'stats', key: 'action_max' },
  { label: '行动限下限', source: 'stats', key: 'action_min' },
]

/** 长表默认展示的核心统计；其余（σ 倍数、CPK 家族、警告/行动限）按需展开。 */
const CORE_STAT_KEYS = new Set(['spec_max', 'spec_min', 'mean', 'max', 'min', 'cpk', 'cpk_level'])

/** 录入框是单行 Input；Excel 导入或粘贴可能带入内部换行，汇总矩阵按单行显示。 */
function toSingleLine(text: string): string {
  return text.replace(/\s*[\r\n]+\s*/g, '')
}

/** 相邻同 group_name 的列聚合成一级表头（columnGroup）。 */
function buildItemColumns(
  section: AprSummarySection,
  onTrend: (item: AprItem) => void,
  flashCellId: string | null,
): ColumnsType<AprSummaryRow> {
  const items = section.items
  const leaf = (item: AprItem, groupStart: boolean): ColumnType<AprSummaryRow> => {
    const numeric = item.value_type === 'number'
    return {
      key: item.id,
      title: (
        <div className={AprChromeStyles.colHead}>
          <div className={AprChromeStyles.colNameRow}>
            <span className={AprChromeStyles.colName}>
              {item.name_cn}
              {item.code.endsWith('#min') ? ' MIN' : item.code.endsWith('#max') ? ' MAX' : ''}
            </span>
            {item.trend_enabled && numeric && (
              <Tooltip title={`看 ${item.name_cn} 随批次的走势`}>
                <button
                  type="button"
                  className={AprChromeStyles.trendButton}
                  aria-label={`看 ${item.name_cn} 的趋势`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onTrend(item)
                  }}
                >
                  <LineChartOutlined />
                </button>
              </Tooltip>
            )}
          </div>
          <div
            className={AprChromeStyles.colSpec}
            title={item.spec_text || item.unit || undefined}
          >
            {item.spec_text || (item.unit ?? '')}
          </div>
        </div>
      ),
      width: 128,
      // 汇总矩阵按列读：文字判定与数值都居中，纵向扫列时不会左右跳。
      align: 'center',
      // 组界只画在组与组之间；第一组紧贴冻结批号列，加线会和冻结列阴影叠成双线。
      onHeaderCell: () => (groupStart ? { className: AprChromeStyles.groupStart } : {}),
      onCell: (row) => {
        const id = cellDomId(section.id, row.batch_id, row.row_seq, item.id)
        return {
          id,
          className:
            clsx(
              groupStart && AprChromeStyles.groupStart,
              flashCellId === id && AprChromeStyles.cellFlash,
            ) || undefined,
        }
      },
      render: (_v, row) => {
        const cell = row.cells[item.id]
        if (!cell || (cell.num === null && !cell.text)) {
          return <span className={AprChromeStyles.cellEmpty}>—</span>
        }
        if (cell.num != null) {
          return <AprValue value={cell.num} status={cell.status} />
        }
        const text = toSingleLine(cell.text ?? '')
        const body = (
          <span
            className={AprChromeStyles.textValue}
            tabIndex={text.length > 12 ? 0 : undefined}
          >
            {text}
          </span>
        )
        return text.length > 12 ? <Tooltip title={text}>{body}</Tooltip> : body
      },
    }
  }

  const columns: ColumnsType<AprSummaryRow> = []
  let i = 0
  while (i < items.length) {
    const group = items[i].group_name
    if (group) {
      const groupStart = i > 0
      let j = i
      while (j < items.length && items[j].group_name === group) j++
      // 单列组也保留组名：分组是模板里的结构，不能因为只有一列就被铺平
      columns.push({
        title: group,
        onHeaderCell: () => ({
          className: clsx(AprChromeStyles.groupHeadCell, groupStart && AprChromeStyles.groupStart),
        }),
        children: items.slice(i, j).map((item, index) => leaf(item, groupStart && index === 0)),
      })
      i = j
      continue
    }
    columns.push(leaf(items[i], false))
    i++
  }
  return columns
}

/** 单段汇总矩阵：动态列 + 批次行 + 表尾统计（长表默认只展开核心统计）。 */
export function SectionTable({
  section,
  onTrend,
  flashCellId,
}: {
  section: AprSummarySection
  onTrend: (item: AprItem) => void
  flashCellId: string | null
}) {
  // 长表（表内滚动）默认收起部分统计，避免 22 行固定表尾占掉表体；短表直接全量展示。
  const scrollY =
    section.rows.length > TABLE_INNER_SCROLL_MIN_ROWS ? TABLE_SCROLL_Y : undefined
  const [showAllStats, setShowAllStats] = useState(() => !scrollY)
  const baseColumns: ColumnsType<AprSummaryRow> = [
    // 序号只是行号：seq 仅用于排序（含导出），不在矩阵里露出，避免和行号混成两种口径。
    {
      title: '序号',
      key: 'row_index',
      width: 58,
      fixed: 'left',
      align: 'center',
      render: (_v, _row, index) => <span className={AprChromeStyles.rowIndex}>{index + 1}</span>,
    },
    {
      title: '批号',
      dataIndex: 'batch_no',
      width: 156,
      fixed: 'left',
      render: (value: string) => <span className={AprChromeStyles.batchNo}>{value}</span>,
    },
  ]
  if (section.multi_row) {
    baseColumns.push({
      title: '行',
      key: 'row_label',
      width: 78,
      fixed: 'left',
      align: 'center',
      render: (_v, row) => row.row_label || `第 ${row.row_seq} 行`,
    })
  }
  const columns: ColumnsType<AprSummaryRow> = [
    ...baseColumns,
    ...buildItemColumns(section, onTrend, flashCellId),
  ]
  // 显式给出矩阵宽度：列多时横向滚动，列少时由 min-width:100% 撑满，避免 'max-content' 多出一条细滚动条。
  const scrollX = (section.multi_row ? 292 : 214) + section.items.length * 128
  const labelSpan = section.multi_row ? 3 : 2

  // 统计值按列精度展示（空=2）；不适用（单限缺对侧/文字列）显示 N/A；CPK级别等文字原样透出
  const fmtStat = (item: AprItem, value: number | string | null | undefined) => {
    if (value === null || value === undefined || value === '') return 'N/A'
    if (typeof value === 'string') return value
    return value.toFixed(item.stat_precision ?? 2)
  }
  // 统计表脚只在有数值统计时出现；展开按钮放在表格外，列多横向滚动时也始终可见。
  const hasStats = section.items.some((item) => section.column_stats[item.id])
  // 未检出批次行：口径透明（zero 已按 0 进统计，exclude 只计未进样本的批数）
  const ndOf = (item: AprItem) => section.column_stats[item.id]?.nd_count ?? 0
  const hasNd = section.items.some((item) => section.column_stats[item.id] && ndOf(item) > 0)

  return (
    <>
      <Table<AprSummaryRow>
        rowKey={(r) => `${r.batch_id}-${r.row_seq}`}
        size="small"
        columns={columns}
        dataSource={section.rows}
        pagination={false}
        tableLayout="fixed"
        scroll={{ x: scrollX, y: scrollY }}
        locale={{
          emptyText: (
            <EmptyState
              title={`${section.name} 该年度还没有批次`}
              hint="在「数据录入」里登记并填写批次值后，这里会按批号逐行汇总。"
            />
          ),
        }}
        summary={() => {
          if (!hasStats) return null
          const visibleStatRows = showAllStats
            ? STAT_FOOTER_ROWS
            : STAT_FOOTER_ROWS.filter((row) => CORE_STAT_KEYS.has(row.key))
          return (
            <Table.Summary fixed={!!scrollY}>
              {visibleStatRows.map(({ label, source, key }) => (
                <Table.Summary.Row key={label}>
                  <Table.Summary.Cell index={0} colSpan={labelSpan}>
                    <span className={AprChromeStyles.statLabel}>{label}</span>
                  </Table.Summary.Cell>
                  {section.items.map((item, index) => {
                    const value =
                      source === 'item'
                        ? item[key as 'spec_min' | 'spec_max']
                        : section.column_stats[item.id]?.[key as keyof AprTrendStats]
                    const display = fmtStat(item, value)
                    return (
                      <Table.Summary.Cell
                        key={item.id}
                        index={labelSpan + index}
                        // 与数据列同轴居中；N/A 和数值都落在列中心。
                        align="center"
                      >
                        <span className={clsx(AprChromeStyles.num, AprChromeStyles.statValue)}>
                          {display}
                        </span>
                      </Table.Summary.Cell>
                    )
                  })}
                </Table.Summary.Row>
              ))}
              {hasNd && (
                <Table.Summary.Row key="nd">
                  <Table.Summary.Cell index={0} colSpan={labelSpan}>
                    <span className={AprChromeStyles.statLabel}>未检出</span>
                  </Table.Summary.Cell>
                  {section.items.map((item, index) => (
                    <Table.Summary.Cell
                      key={item.id}
                      index={labelSpan + index}
                      align="center"
                    >
                      <span className={AprChromeStyles.statNote}>
                        {ndOf(item) > 0 ? `${ndOf(item)} 批` : ''}
                      </span>
                    </Table.Summary.Cell>
                  ))}
                </Table.Summary.Row>
              )}
            </Table.Summary>
          )
        }}
      />
      {hasStats && (
        <div className={AprChromeStyles.statToggleBar}>
          <Button
            type="link"
            size="small"
            onClick={() => setShowAllStats((value) => !value)}
          >
            {showAllStats
              ? '收起部分统计'
              : `展开全部 ${STAT_FOOTER_ROWS.length} 项统计`}
          </Button>
        </div>
      )}
    </>
  )
}
