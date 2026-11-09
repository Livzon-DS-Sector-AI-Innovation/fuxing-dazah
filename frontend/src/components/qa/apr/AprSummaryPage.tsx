'use client'

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Select,
  Skeleton,
  Space,
  Table,
  Tooltip,
} from 'antd'
import type { ColumnsType, ColumnType } from 'antd/es/table'
import { DownloadOutlined, LineChartOutlined, LockOutlined, UnlockOutlined } from '@ant-design/icons'
import {
  actionError,
  EmptyState,
  qaWidePageStyle,
} from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { AprTrendChart } from './AprTrendChart'
import { lockAprYear } from '@/actions/qa-apr'
import { aprSummaryExportUrl, fetchAprProducts, fetchAprSummary, fetchAprTrend } from '@/lib/api/qa-apr'
import type { AprItem, AprSummary, AprSummaryRow, AprSummarySection } from '@/types/qa-apr'
import {
  AprChromeStyles,
  AprMeta,
  AprScopeBar,
  AprSegmented,
  AprSheet,
  AprStamp,
  AprValue,
  AprYearTabs,
} from './AprChrome'
import { confirmAsync, DATA_KIND_LABEL } from './AprConfigShared'

type ExceptionKind = 'oos' | 'oot'

/** 结论条里直接列出的越界项上限，超出部分指向下方各段明细。 */
const MAX_EXCEPTION_ROWS = 12

interface AprException {
  key: string
  sectionId: string
  sectionName: string
  batchNo: string
  rowLabel: string | null
  itemName: string
  value: string
  unit: string | null
  status: ExceptionKind
}

/** 相邻同 group_name 的列聚合成一级表头（columnGroup）。 */
function buildItemColumns(
  items: AprItem[],
  onTrend: (item: AprItem) => void,
): ColumnsType<AprSummaryRow> {
  const leaf = (item: AprItem): ColumnType<AprSummaryRow> => ({
    key: item.id,
    title: (
      <div style={{ lineHeight: 1.35 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'flex-end', gap: 4 }}>
          <span style={{ whiteSpace: 'normal' }}>
            {item.name_cn}
            {item.code.endsWith('#min') ? ' MIN' : item.code.endsWith('#max') ? ' MAX' : ''}
          </span>
          {item.trend_enabled && item.value_type === 'number' && (
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
        <div style={{ fontSize: 11, color: 'var(--color-steel)', whiteSpace: 'normal' }}>
          {item.spec_text || (item.unit ?? '')}
        </div>
      </div>
    ),
    width: 128,
    align: 'right',
    render: (_v, row) => {
      const cell = row.cells[item.id]
      if (!cell || (cell.num === null && !cell.text)) {
        return <span style={{ color: 'var(--color-hairline-strong)' }}>—</span>
      }
      return (
        <AprValue
          value={cell.num ?? cell.text ?? ''}
          status={cell.status}
          unit={cell.num != null ? item.unit : null}
        />
      )
    },
  })

  const columns: ColumnsType<AprSummaryRow> = []
  let i = 0
  while (i < items.length) {
    const group = items[i].group_name
    if (group) {
      let j = i
      while (j < items.length && items[j].group_name === group) j++
      // 单列组也保留组名：分组是模板里的结构，不能因为只有一列就被铺平
      columns.push({ title: group, children: items.slice(i, j).map(leaf) })
      i = j
      continue
    }
    columns.push(leaf(items[i]))
    i++
  }
  return columns
}

function SectionTable({
  section,
  onTrend,
}: {
  section: AprSummarySection
  onTrend: (item: AprItem) => void
}) {
  const baseColumns: ColumnsType<AprSummaryRow> = [
    // 序号只是行号：seq 仅用于排序（含导出），不在矩阵里露出，避免和行号混成两种口径。
    { title: '序号', key: 'row_index', width: 58, render: (_v, _row, index) => index + 1 },
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
      render: (_v, row) => row.row_label || `第 ${row.row_seq} 行`,
    })
  }
  const columns: ColumnsType<AprSummaryRow> = [...baseColumns, ...buildItemColumns(section.items, onTrend)]
  // 显式给出矩阵宽度：列多时横向滚动，列少时由 min-width:100% 撑满，避免 'max-content' 多出一条细滚动条。
  const scrollX = (section.multi_row ? 292 : 214) + section.items.length * 128

  const statsOf = (item: AprItem, key: 'mean' | 'max' | 'min' | 'stdev') => {
    const stats = section.column_stats[item.id]
    const value = stats?.[key]
    return value === undefined ? '' : Number(value).toFixed(4).replace(/\.?0+$/, '')
  }

  const statLabelStyle = {
    display: 'block',
    textAlign: 'right' as const,
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--color-steel)',
    whiteSpace: 'nowrap' as const,
  }

  return (
    <Table<AprSummaryRow>
      rowKey={(r) => `${r.batch_id}-${r.row_seq}`}
      size="small"
      columns={columns}
      dataSource={section.rows}
      pagination={false}
      tableLayout="fixed"
      scroll={{ x: scrollX }}
      locale={{
        emptyText: (
          <EmptyState
            title={`${section.name} 该年度还没有批次`}
            hint="在「数据录入」里登记并填写批次值后，这里会按批号逐行汇总。"
          />
        ),
      }}
      summary={() => {
        const numericItems = section.items.filter((i) => section.column_stats[i.id])
        if (numericItems.length === 0) return null
        const statRow = (label: string, key: 'mean' | 'max' | 'min' | 'stdev') => (
          <Table.Summary.Row key={key}>
            <Table.Summary.Cell index={0} colSpan={section.multi_row ? 3 : 2}>
              <span style={statLabelStyle}>{label}</span>
            </Table.Summary.Cell>
            {section.items.map((item) => {
              const value = section.column_stats[item.id] ? statsOf(item, key) : ''
              return (
                <Table.Summary.Cell key={item.id} index={0} align="right">
                  <span className={AprChromeStyles.num} style={{ fontSize: 12, color: 'var(--color-slate)' }}>
                    {value}
                    {value && item.unit ? (
                      <span className={AprChromeStyles.unit}>{item.unit}</span>
                    ) : null}
                  </span>
                </Table.Summary.Cell>
              )
            })}
          </Table.Summary.Row>
        )
        // 未检出批次行：口径透明（zero 已按 0 进上面统计，exclude 只计未进样本的批数）
        const ndOf = (item: AprItem) => section.column_stats[item.id]?.nd_count ?? 0
        const hasNd = numericItems.some((i) => ndOf(i) > 0)
        return (
          <Table.Summary>
            {statRow('平均值', 'mean')}
            {statRow('最大值', 'max')}
            {statRow('最小值', 'min')}
            {statRow('σ', 'stdev')}
            {hasNd && (
              <Table.Summary.Row key="nd">
                <Table.Summary.Cell index={0} colSpan={section.multi_row ? 3 : 2}>
                  <span style={statLabelStyle}>未检出</span>
                </Table.Summary.Cell>
                {section.items.map((item) => (
                  <Table.Summary.Cell key={item.id} index={0} align="right">
                    <span style={{ fontSize: 12, color: 'var(--color-steel)' }}>
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
  )
}

// ═════════════════════════ 越界清单 ═════════════════════════

function collectExceptions(summary: AprSummary | null): AprException[] {
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
          batchNo: row.batch_no,
          rowLabel: section.multi_row ? row.row_label || `第 ${row.row_seq} 行` : null,
          itemName: `${item.name_cn}${item.code.endsWith('#min') ? ' MIN' : item.code.endsWith('#max') ? ' MAX' : ''}`,
          value: String(cell.num ?? cell.text ?? ''),
          unit: item.unit,
          status: cell.status,
        })
      }
    }
  }
  // 超标排在预警前面：先看最严重的。
  return list.sort((a, b) => (a.status === b.status ? 0 : a.status === 'oos' ? -1 : 1))
}

function AprExceptions({ exceptions, flush = false }: { exceptions: AprException[]; flush?: boolean }) {
  const oos = exceptions.filter((e) => e.status === 'oos').length
  const oot = exceptions.length - oos
  const box = flush
    ? `${AprChromeStyles.exceptions} ${AprChromeStyles.exceptionsFlush}`
    : AprChromeStyles.exceptions

  if (exceptions.length === 0) {
    return (
      <div className={`${box} ${flush ? '' : AprChromeStyles.exceptionsClean}`}>
        <div className={AprChromeStyles.exceptionsHead}>
          <span className={AprChromeStyles.count}>
            <span className={`${AprChromeStyles.countValue} ${AprChromeStyles.countValueClean}`}>0</span>
            <span className={AprChromeStyles.countLabel}>越界项</span>
          </span>
          <span className={AprChromeStyles.exceptionsNote}>
            本年度已录入的批值与标准限度、OOT 预警限全部相符，可以直接定稿。
          </span>
        </div>
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
        <span className={AprChromeStyles.exceptionsNote}>点一行跳到该段明细</span>
      </div>
      <div className={AprChromeStyles.exceptionsList} role="list">
        {exceptions.slice(0, MAX_EXCEPTION_ROWS).map((exception) => (
          <button
            key={exception.key}
            type="button"
            role="listitem"
            className={AprChromeStyles.exceptionRow}
            onClick={() => {
              document
                .getElementById(`apr-section-${exception.sectionId}`)
                ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
            }}
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
      </div>
    </div>
  )
}

// ═════════════════════════ 页面 ═════════════════════════

export function AprSummaryPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  // 锁定/导出按独立权限码显隐：只读用户不依赖点击后的 403 兜底
  const canLock = hasPermission('qa:apr:lock')
  const canExport = hasPermission('qa:apr:export')
  const [productId, setProductId] = useState<string | null>(null)
  const [year, setYear] = useState<number>(new Date().getFullYear())
  const [dataKind, setDataKind] = useState<string>('all')
  const [trendItem, setTrendItem] = useState<AprItem | null>(null)
  const [trendScope, setTrendScope] = useState<'year' | 'all'>('year')
  const [locking, setLocking] = useState(false)

  const productsQuery = useQuery({
    queryKey: ['qa', 'apr', 'products', 'active'],
    queryFn: () => fetchAprProducts(true),
  })
  const products = productsQuery.data ?? []

  const summaryQuery = useQuery({
    queryKey: ['qa', 'apr', 'summary', productId, year, dataKind],
    queryFn: () =>
      fetchAprSummary({
        product_id: productId!,
        year,
        data_kind: dataKind === 'all' ? undefined : (dataKind as 'production' | 'inspection'),
      }),
    enabled: !!productId,
    placeholderData: keepPreviousData,
  })
  const summary = summaryQuery.data ?? null

  const trendQuery = useQuery({
    queryKey: ['qa', 'apr', 'trend', trendItem?.id, trendScope, year],
    queryFn: () => fetchAprTrend(trendItem!.id, trendScope === 'year' ? year : undefined),
    enabled: !!trendItem,
  })

  const sections = useMemo(() => summary?.sections ?? [], [summary])
  const exceptions = useMemo(() => collectExceptions(summary), [summary])
  const batchCount = sections.reduce((sum, section) => sum + section.rows.length, 0)

  const years = useMemo(() => {
    const known = new Set<number>([...(summary?.batch_years ?? []), new Date().getFullYear(), year])
    return [...known].sort((a, b) => b - a)
  }, [summary, year])

  const handleLockToggle = (locked: boolean) => {
    if (!productId) return
    confirmAsync(modal, {
      title: locked ? `锁定 ${year} 年度` : `解锁 ${year} 年度`,
      content: locked
        ? '锁定后该年度所有批次与录入值不可修改（年终定稿）。'
        : '解锁后该年度数据可继续修改。',
      okText: locked ? '锁定' : '解锁',
      cancelText: '取消',
      onOk: async () => {
        setLocking(true)
        try {
          const result = await lockAprYear(productId, year, locked)
          if (!result.success) {
            message.error(actionError(result))
            return
          }
          message.success(locked ? '年度已锁定' : '年度已解锁')
          void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'summary'] })
          void queryClient.invalidateQueries({ queryKey: ['qa', 'apr', 'batches'] })
        } finally {
          setLocking(false)
        }
      },
    })
  }

  return (
    <div style={qaWidePageStyle}>
      <PageHeading
        title="汇总分析"
        subtitle="年度回顾表：批次为行、质量属性为列，附均值与 σ，越界项单独列出。定稿后锁定并导出 Excel。"
        actions={
          productId && (canLock || canExport) ? (
            <Space size={6}>
              {canLock && (
                <Tooltip title={summary?.locked ? '解除锁定后可继续修改' : '定稿后冻结该年度数据'}>
                  <Button
                    icon={summary?.locked ? <UnlockOutlined /> : <LockOutlined />}
                    onClick={() => handleLockToggle(!summary?.locked)}
                    loading={locking}
                  >
                    {summary?.locked ? '解锁年度' : '锁定年度'}
                  </Button>
                </Tooltip>
              )}
              {canExport && (
                <Button
                  type="primary"
                  href={aprSummaryExportUrl(productId, year)}
                  icon={<DownloadOutlined />}
                >
                  导出 Excel
                </Button>
              )}
            </Space>
          ) : undefined
        }
      />

      <AprScopeBar
        lead={
          <Select
            style={{ width: 236 }}
            placeholder="选择产品"
            showSearch
            optionFilterProp="label"
            value={productId}
            onChange={(v) => {
              setProductId(v)
              setTrendItem(null)
            }}
            loading={productsQuery.isLoading}
            options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
          />
        }
        tail={
          <>
            <AprYearTabs
              years={years}
              value={year}
              onChange={(y) => {
                setYear(y)
                setTrendItem(null)
              }}
            />
            <AprSegmented
              ariaLabel="数据类型"
              value={dataKind}
              onChange={setDataKind}
              options={[
                { value: 'all', label: '全部' },
                { value: 'production', label: '生产' },
                { value: 'inspection', label: '检验' },
              ]}
            />
            {summary?.locked ? (
              <AprStamp tone="locked" icon={<LockOutlined />}>
                已定稿
              </AprStamp>
            ) : productId ? (
              <AprStamp tone="open">开放</AprStamp>
            ) : null}
          </>
        }
      />

      {!productId ? (
        <AprSheet title="年度回顾表" bleed={false} meta={<AprMeta items={['未选产品']} />}>
          <EmptyState
            title="先选一个产品"
            hint="选好产品后按年度汇总：批次逐行，质量属性逐列，越界项单独列出。"
          />
        </AprSheet>
      ) : summaryQuery.isLoading ? (
        <AprSheet title="年度回顾表" bleed={false}>
          <Skeleton active paragraph={{ rows: 5 }} />
        </AprSheet>
      ) : summaryQuery.isError ? (
        <AprSheet title="年度回顾表" bleed={false}>
          <Alert
            type="error"
            showIcon
            title="汇总加载失败"
            description={summaryQuery.error instanceof Error ? summaryQuery.error.message : '请稍后重试'}
            action={
              <Button size="small" onClick={() => void summaryQuery.refetch()}>
                重试
              </Button>
            }
          />
        </AprSheet>
      ) : sections.length === 0 ? (
        <AprSheet title="年度回顾表" bleed={false}>
          <EmptyState
            title={`${year} 年度还没有可汇总的数据`}
            hint="先在「数据录入」登记批次并填写值，或把年度切到有数据的年份。"
            action={
              <Button onClick={() => setDataKind('all')} disabled={dataKind === 'all'}>
                清除数据类型筛选
              </Button>
            }
          />
        </AprSheet>
      ) : (
        <>
          <AprSheet
            title="年度结论"
            meta={
              <AprMeta
                items={[
                  `${year} 年度`,
                  `${sections.length} 个模板段`,
                  `${batchCount} 行批值`,
                  dataKind === 'all' ? '生产与检验' : DATA_KIND_LABEL[dataKind as 'production' | 'inspection'],
                ]}
              />
            }
            footer={
              <span>点列头上的「趋势」查看单指标随批次的走势；越界值带语义色，OOS 红、OOT 橙。</span>
            }
          >
            <AprExceptions exceptions={exceptions} flush />
          </AprSheet>

          {sections.map((section) => (
            <div key={section.id} id={`apr-section-${section.id}`}>
              <AprSheet
                title={section.name}
                meta={
                  <AprMeta
                    items={[
                      DATA_KIND_LABEL[section.data_kind],
                      section.market,
                      section.multi_row ? '一批多行' : '一批一行',
                      `${section.rows.length} 批`,
                      `${section.items.length} 个质量属性`,
                    ]}
                  />
                }
                footer={
                  <span>
                    数值列下方为列统计（平均 / 最大 / 最小 / σ）；越界值带语义色并标在「年度结论」里。
                  </span>
                }
              >
                <SectionTable section={section} onTrend={setTrendItem} />
              </AprSheet>
            </div>
          ))}

          {trendItem ? (
            <AprSheet
              title={`趋势：${trendItem.name_cn}`}
              meta={
                <AprMeta
                  items={[
                    trendItem.unit,
                    trendItem.spec_text ? `标准 ${trendItem.spec_text}` : false,
                    trendItem.oot_min != null || trendItem.oot_max != null ? '含 OOT 预警限' : false,
                  ]}
                />
              }
              bleed={false}
              actions={
                <AprSegmented
                  ariaLabel="趋势范围"
                  value={trendScope}
                  onChange={setTrendScope}
                  options={[
                    { value: 'year', label: `${year} 年` },
                    { value: 'all', label: '跨年' },
                  ]}
                />
              }
            >
              <AprTrendChart
                trend={trendQuery.data ?? null}
                loading={trendQuery.isLoading}
                error={
                  trendQuery.isError
                    ? trendQuery.error instanceof Error
                      ? trendQuery.error.message
                      : '趋势加载失败'
                    : null
                }
              />
            </AprSheet>
          ) : null}
        </>
      )}
    </div>
  )
}
