'use client'

import { useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Select,
  Skeleton,
  Space,
  Tooltip,
} from 'antd'
import {
  DownloadOutlined,
  FileWordOutlined,
  LockOutlined,
  UnlockOutlined,
} from '@ant-design/icons'
import {
  actionError,
  EmptyState,
  qaWidePageStyle,
} from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { AprTrendModal } from './AprTrendModal'
import { lockAprYear } from '@/actions/qa'
import {
  aprSectionExportUrl,
  aprSectionReportUrl,
  fetchAprProducts,
  fetchAprSummary,
  fetchAprTrend,
} from '@/lib/api/qa'
import type { AprItem } from '@/types/qa'
import {
  AprChromeStyles,
  AprMeta,
  AprScopeBar,
  AprSegmented,
  AprSheet,
  AprStamp,
  AprYearTabs,
  prefersReducedMotion,
} from './AprChrome'
import { confirmAsync, DATA_KIND_LABEL } from './AprConfigShared'
import { AprExceptions, collectExceptions, type AprException } from './AprExceptions'
import { SectionTable, cellDomId } from './AprSectionTable'

// ═════════════════════════ 页面 ═════════════════════════

export function AprSummaryPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  // 锁定/导出按独立权限码显隐：只读用户不依赖点击后的 403 兜底
  const canLock = hasPermission('qa:apr:lock')
  const canExport = hasPermission('qa:apr:export')
  const router = useRouter()
  const searchParams = useSearchParams()
  const productParam = searchParams.get('product')
  // 选择同步进 URL（?product=&year=&kind=），刷新/分享链接都能恢复现场；
  // 产品用短码而不是 UUID，与录入页保持同一套约定。
  const [pickedProductId, setPickedProductId] = useState<string | null>(null)
  const [year, setYear] = useState<number>(() => {
    const raw = Number(searchParams.get('year'))
    return Number.isInteger(raw) && raw >= 2000 && raw <= 2100 ? raw : new Date().getFullYear()
  })
  const [dataKind, setDataKind] = useState<string>(() => {
    const raw = searchParams.get('kind')
    return raw === 'production' || raw === 'inspection' ? raw : 'all'
  })
  const [trendItem, setTrendItem] = useState<AprItem | null>(null)
  const [trendScope, setTrendScope] = useState<'year' | 'all'>('year')
  const [locking, setLocking] = useState(false)
  const [flashCellId, setFlashCellId] = useState<string | null>(null)
  const flashTimer = useRef<number | null>(null)

  const productsQuery = useQuery({
    queryKey: ['qa', 'apr', 'products', 'active'],
    queryFn: () => fetchAprProducts(true),
  })
  const products = productsQuery.data ?? []
  // 显式选择 > URL 产品短码 > 第一个启用产品；派生而非 state，不写回 URL。
  const pickedProduct = products.some((product) => product.id === pickedProductId)
    ? pickedProductId
    : null
  const urlProduct = productParam
    ? products.find((product) => product.code === productParam) ?? null
    : null
  const productId = pickedProduct ?? urlProduct?.id ?? products[0]?.id ?? null
  const productCode = products.find((product) => product.id === productId)?.code ?? null

  /** 用本次意图值直接重建 URL：连续切换时 searchParams 可能还没提交，按它合并会丢参数。 */
  const syncUrl = (patch: { product?: string | null; year?: number; kind?: string }) => {
    const nextProduct = patch.product === undefined ? productCode : patch.product
    const nextYear = patch.year ?? year
    const nextKind = patch.kind === undefined ? dataKind : patch.kind
    const params = new URLSearchParams()
    if (nextProduct) params.set('product', nextProduct)
    params.set('year', String(nextYear))
    if (nextKind !== 'all') params.set('kind', nextKind)
    router.replace(`/qa/apr/summary?${params.toString()}`, { scroll: false })
  }

  const handleProductChange = (nextProductId: string) => {
    setPickedProductId(nextProductId)
    setTrendItem(null)
    syncUrl({ product: products.find((product) => product.id === nextProductId)?.code ?? null })
  }

  const handleYearChange = (nextYear: number) => {
    setYear(nextYear)
    setTrendItem(null)
    syncUrl({ year: nextYear })
  }

  const handleDataKindChange = (nextKind: string) => {
    setDataKind(nextKind)
    syncUrl({ kind: nextKind })
  }

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
  const fetching = summaryQuery.isFetching && !summaryQuery.isLoading
  // keepPreviousData 期间 summary 还是上一个产品/年度的：锁定状态、完整性和跳转都不能用它。
  const summaryReady =
    !summaryQuery.isLoading && !summaryQuery.isPlaceholderData && !summaryQuery.isError

  /** 必填完整性：锁定接口只要求「至少一批」，定稿前把空白必填格显式列出来。 */
  const missingRequired = useMemo(() => {
    let count = 0
    let firstSectionName: string | null = null
    for (const section of sections) {
      for (const row of section.rows) {
        for (const item of section.items) {
          if (!item.required) continue
          const cell = row.cells[item.id]
          if (cell && (cell.num != null || cell.text?.trim())) continue
          count += 1
          firstSectionName ??= section.name
        }
      }
    }
    return { count, firstSectionName }
  }, [sections])
  const missingCount = missingRequired.count
  const fixHref = useMemo(() => {
    if (!summaryReady || missingCount === 0 || !productCode || !missingRequired.firstSectionName) {
      return null
    }
    const params = new URLSearchParams({ product: productCode, year: String(year) })
    params.set('section', missingRequired.firstSectionName)
    return `/qa/apr/entry?${params.toString()}`
  }, [
    summaryReady,
    missingCount,
    missingRequired.firstSectionName,
    productCode,
    year,
  ])

  /** 越界清单点击：直接定位到该单元格并短暂高亮，找不到时退回段首。 */
  const jumpToException = (exception: AprException) => {
    const id = cellDomId(
      exception.sectionId,
      exception.batchId,
      exception.rowSeq,
      exception.itemId,
    )
    const cell = document.getElementById(id)
    if (!cell) {
      document.getElementById(`apr-section-${exception.sectionId}`)?.scrollIntoView({
        block: 'start',
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      })
      return
    }
    cell.scrollIntoView({
      block: 'center',
      inline: 'center',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    })
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    setFlashCellId(id)
    flashTimer.current = window.setTimeout(() => {
      setFlashCellId((current) => (current === id ? null : current))
    }, 1600)
  }

  const years = useMemo(() => {
    const known = new Set<number>([...(summary?.batch_years ?? []), new Date().getFullYear(), year])
    return [...known].sort((a, b) => b - a)
  }, [summary, year])

  const handleLockToggle = (locked: boolean) => {
    if (!productId || !summaryReady) return
    confirmAsync(modal, {
      title: locked ? `锁定 ${year} 年度` : `解锁 ${year} 年度`,
      content: locked
        ? `${missingCount > 0 ? `当前还有 ${missingCount} 个必填格未填写。` : ''}锁定后该年度所有批次与录入值不可修改（年终定稿）。`
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
        subtitle="年度回顾表：批次为行、质量属性为列，表尾全量统计（±3σ/±4σ/CPK/警告与行动限），越界项单独列出；Excel 与 Word 报告按模板段导出。"
      />

      <AprScopeBar
        lead={
          <Select
            style={{ width: 236 }}
            placeholder="选择产品"
            showSearch
            optionFilterProp="label"
            value={productId}
            onChange={handleProductChange}
            loading={productsQuery.isLoading}
            options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
          />
        }
        tail={
          <>
            <AprYearTabs
              years={years}
              value={year}
              onChange={handleYearChange}
            />
            <AprSegmented
              ariaLabel="数据类型"
              value={dataKind}
              onChange={handleDataKindChange}
              options={[
                { value: 'all', label: '全部' },
                { value: 'production', label: '生产' },
                { value: 'inspection', label: '检验' },
              ]}
            />
            {fetching && (
              <span className={AprChromeStyles.fetching} role="status">
                更新中…
              </span>
            )}
            {productId && canLock && summaryReady && (
              <Tooltip title={summary?.locked ? '解除锁定后可继续修改' : '定稿后冻结该年度数据'}>
                <Button
                  size="small"
                  icon={summary?.locked ? <UnlockOutlined /> : <LockOutlined />}
                  onClick={() => handleLockToggle(!summary?.locked)}
                  loading={locking}
                >
                  {summary?.locked ? '解锁年度' : '锁定年度'}
                </Button>
              </Tooltip>
            )}
            {summaryReady ? (
              summary?.locked ? (
                <AprStamp tone="locked" icon={<LockOutlined />}>
                  已定稿
                </AprStamp>
              ) : productId ? (
                <AprStamp tone="open">开放</AprStamp>
              ) : null
            ) : null}
          </>
        }
      />

      {productsQuery.isLoading ? (
        <AprSheet title="年度回顾表" bleed={false}>
          <Skeleton active paragraph={{ rows: 3 }} />
        </AprSheet>
      ) : !productId ? (
        <AprSheet title="年度回顾表" bleed={false} meta={<AprMeta items={['未选产品']} />}>
          <EmptyState
            title={products.length === 0 ? '还没有启用的产品' : '先选一个产品'}
            hint={
              products.length === 0
                ? '先到「模板配置」新增产品并添加模板段，这里才能按年度汇总。'
                : '选好产品后按年度汇总：批次逐行，质量属性逐列，越界项单独列出。'
            }
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
              <Button onClick={() => handleDataKindChange('all')} disabled={dataKind === 'all'}>
                清除数据类型筛选
              </Button>
            }
          />
        </AprSheet>
      ) : (
        <div
          aria-busy={fetching}
          style={{ opacity: fetching ? 0.55 : 1, transition: 'opacity 120ms ease' }}
        >
          <AprSheet
            title="年度结论"
            meta={
              <AprMeta
                items={[
                  `${year} 年度`,
                  `${sections.length} 个模板段`,
                  `${batchCount} 行批值`,
                  missingCount > 0 ? `${missingCount} 个必填格未填` : false,
                  dataKind === 'all' ? '生产与检验' : DATA_KIND_LABEL[dataKind as 'production' | 'inspection'],
                ]}
              />
            }
            footer={
              <span>列头「趋势」看单指标随批次的走势；越界值带语义色，OOS 红、OOT 橙。</span>
            }
          >
            <AprExceptions
              exceptions={exceptions}
              rowCount={batchCount}
              missingCount={missingCount}
              fixHref={fixHref}
              onJump={jumpToException}
              flush
            />
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
                actions={
                  canExport ? (
                    <Space size={6}>
                      <Tooltip title={`下载 ${section.name} ${year} 汇总（模板数据 + 全量统计）`}>
                        <Button
                          size="small"
                          icon={<DownloadOutlined />}
                          href={aprSectionExportUrl(section.id, year)}
                        >
                          导出 Excel
                        </Button>
                      </Tooltip>
                      <Tooltip title={`下载 ${section.name} ${year} 年度回顾 Word 报告（趋势图 + CPK 结论）`}>
                        <Button
                          size="small"
                          icon={<FileWordOutlined />}
                          href={aprSectionReportUrl(section.id, year)}
                        >
                          导出报告
                        </Button>
                      </Tooltip>
                    </Space>
                  ) : undefined
                }
              >
                <SectionTable
                  key={`${section.id}-${year}-${dataKind}`}
                  section={section}
                  onTrend={setTrendItem}
                  flashCellId={flashCellId}
                />
              </AprSheet>
            </div>
          ))}

        </div>
      )}

      <AprTrendModal
        item={trendItem}
        year={year}
        scope={trendScope}
        onScopeChange={setTrendScope}
        onClose={() => setTrendItem(null)}
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
    </div>
  )
}
