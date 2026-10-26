'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useRouter } from 'next/navigation'
import { App, Button, DatePicker, Grid, Input, Select, Space, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import * as XLSX from 'xlsx'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { fetchDeviationSummary, fetchDeviations } from '@/lib/api/qa-deviation'
import {
  DEVIATION_CLASSIFICATION_LABEL,
  DEVIATION_STATUS_LABEL,
  QUALITY_IMPACT_LABEL,
  ROOT_CAUSE_CATEGORY_LABEL,
  type DeviationBrief,
  type DeviationClassification,
  type DeviationStatus,
  type RootCauseCategory,
} from '@/types/qa-deviation'
import { DeviationCreateModal } from './DeviationCreateModal'
import { ClassificationPill, DeviationStatusPill, DueDateCell, EmptyState, PILL, cardStyle, fmtDate, tabularNums, toOptions } from './shared'
import styles from './DeviationLedger.module.css'

const PAGE_SIZE = 20
const STATUS_ORDER: DeviationStatus[] = ['draft', 'investigating', 'assessing', 'closed']

type StatusFilter = DeviationStatus | 'all' | 'overdue'

const pillTabStyle = (active: boolean, danger = false): CSSProperties => {
  const accent = danger ? '#e03131' : '#000000'
  return {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '4px 14px',
    fontSize: 13,
    fontWeight: 500,
    lineHeight: '22px',
    color: active ? '#ffffff' : danger ? '#e03131' : '#787671',
    background: active ? accent : 'transparent',
    border: `1px solid ${active ? accent : '#e5e3df'}`,
    borderRadius: 9999,
    cursor: 'pointer',
    fontFamily: 'inherit',
    fontVariantNumeric: 'tabular-nums',
  }
}

const tabCountStyle = (active: boolean): CSSProperties => ({
  marginLeft: 6,
  fontSize: 12,
  color: active ? 'rgba(255,255,255,0.72)' : '#a4a097',
})

export function DeviationLedgerPage() {
  const { message } = App.useApp()
  const router = useRouter()
  const screens = Grid.useBreakpoint()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('qa:deviation:create')

  const [keyword, setKeyword] = useState('')
  const [queryKeyword, setQueryKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [classification, setClassification] = useState<DeviationClassification | undefined>()
  const [rootCause, setRootCause] = useState<RootCauseCategory | undefined>()
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const queryClient = useQueryClient()

  const listParams = useMemo(
    () => ({
      keyword: queryKeyword.trim() || undefined,
      status: statusFilter === 'all' || statusFilter === 'overdue' ? undefined : statusFilter,
      overdue_only: statusFilter === 'overdue' || undefined,
      classification,
      root_cause_category: rootCause,
      discovery_from: range?.[0]?.format('YYYY-MM-DD'),
      discovery_to: range?.[1]?.format('YYYY-MM-DD'),
    }),
    [classification, queryKeyword, range, rootCause, statusFilter],
  )

  // 列表与状态统计都走 React Query；翻页保留上一页数据避免表格闪烁。
  const listQuery = useQuery({
    queryKey: ['qa', 'deviations', listParams, page],
    queryFn: () => fetchDeviations({ ...listParams, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const summaryQuery = useQuery({
    queryKey: ['qa', 'deviations', 'summary'],
    queryFn: fetchDeviationSummary,
  })
  const { isError } = listQuery
  useEffect(() => {
    if (isError) message.error('加载偏差台账失败')
  }, [isError, message])

  const rows = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const loading = listQuery.isFetching
  const summary: Partial<Record<DeviationStatus, number>> = summaryQuery.data ?? {}
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['qa', 'deviations'] })

  const handleExport = async () => {
    setExporting(true)
    try {
      // 按当前筛选导出，最多 1000 行，够一本年度台账。
      const all: DeviationBrief[] = []
      for (let current = 1; current <= 5; current += 1) {
        const result = await fetchDeviations({ ...listParams, page: current, page_size: 200 })
        all.push(...result.items)
        if (all.length >= result.total) break
      }
      const sheetRows = all.map((row) => ({
        偏差编号: row.deviation_no,
        状态: DEVIATION_STATUS_LABEL[row.status],
        发现日期: row.discovery_date,
        发生日期: row.occurrence_date ?? '',
        关闭期限: row.due_date,
        关闭日期: row.closed_at ? fmtDate(row.closed_at) : '',
        发生部门: row.department_name ?? '',
        组别: row.group_name ?? '',
        发现人: row.reporter_name ?? '',
        质量员: row.qa_person_name ?? '',
        偏差概述: row.description,
        偏差分类: row.classification ? DEVIATION_CLASSIFICATION_LABEL[row.classification] : '',
        根本原因分类: row.root_cause_category ? ROOT_CAUSE_CATEGORY_LABEL[row.root_cause_category] : '',
        质量影响: row.quality_impact ? QUALITY_IMPACT_LABEL[row.quality_impact] : '',
        是否重复: row.is_repeat ? '是' : '否',
        是否发起CAPA: row.capa_initiated === null ? '' : row.capa_initiated ? '是' : '否',
        延期次数: row.extension_count,
      }))
      const workbook = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(sheetRows), '偏差处理台账')
      XLSX.writeFile(workbook, `偏差处理台账_${new Date().toISOString().slice(0, 10)}.xlsx`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const columns: ColumnsType<DeviationBrief> = [
    {
      title: '偏差编号',
      dataIndex: 'deviation_no',
      width: 118,
      render: (value: string, row) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
          <span className={styles.id} style={{ color: '#0075de', fontWeight: 600 }}>{value}</span>
          {(row.reported_late || row.is_repeat) && (
            <span style={{ display: 'inline-flex', gap: 4 }}>
              {row.reported_late && <Tooltip title="登记日晚于发现日次日，超过 24 小时书面报告时限"><span style={PILL.error}>迟报</span></Tooltip>}
              {row.is_repeat && <span style={PILL.purple}>重复</span>}
            </span>
          )}
        </div>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 82, render: (value: DeviationStatus) => <DeviationStatusPill status={value} /> },
    { title: '发现日期', dataIndex: 'discovery_date', width: 110, render: (value: string) => <span style={{ ...tabularNums, whiteSpace: 'nowrap' }}>{fmtDate(value)}</span> },
    {
      title: '关闭期限',
      dataIndex: 'due_date',
      width: 128,
      render: (_: string, row) => (
        <DueDateCell dueDate={row.due_date} daysRemaining={row.days_remaining} isOverdue={row.is_overdue} closed={row.status === 'closed'} />
      ),
    },
    {
      title: '发生部门',
      dataIndex: 'department_name',
      width: 128,
      render: (value: string | null, row) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span>{value || <span style={{ color: '#a4a097' }}>未填</span>}</span>
          {row.group_name && <span style={{ fontSize: 12, color: '#787671' }}>{row.group_name}</span>}
        </div>
      ),
    },
    {
      title: '偏差概述',
      dataIndex: 'description',
      ellipsis: { showTitle: false },
      render: (value: string) => <Tooltip title={value} placement="topLeft"><span>{value}</span></Tooltip>,
    },
    {
      title: '分类 / 根因',
      dataIndex: 'classification',
      width: 112,
      render: (value: DeviationClassification | null, row) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
          <ClassificationPill value={value} />
          {row.root_cause_category && (
            <span style={{ fontSize: 12, color: '#787671' }}>{ROOT_CAUSE_CATEGORY_LABEL[row.root_cause_category]}</span>
          )}
        </div>
      ),
    },
    {
      title: '质量员',
      dataIndex: 'qa_person_name',
      width: 76,
      ellipsis: true,
      render: (value: string | null) => value || <span style={{ color: '#a4a097' }}>—</span>,
    },
  ]

  const fieldFiltered = Boolean(queryKeyword || classification || rootCause || range)
  const filtered = fieldFiltered || statusFilter !== 'all'
  const overdueCount = rows.filter((row) => row.is_overdue).length
  // 超期数只有“整本台账都在当前页”或正在看超期筛选时才是准确值，否则不显示避免误导。
  const overdueBadge = statusFilter === 'overdue' ? total : statusFilter === 'all' && rows.length === total && !fieldFiltered ? overdueCount : null
  const totalCount = STATUS_ORDER.reduce((sum, status) => sum + (summary[status] ?? 0), 0)

  const resetFilters = () => {
    setKeyword('')
    setQueryKeyword('')
    setStatusFilter('all')
    setClassification(undefined)
    setRootCause(undefined)
    setRange(null)
    setPage(1)
  }

  return (
    <div style={{ maxWidth: 1480, margin: '0 auto', paddingBottom: 36 }}>
      <PageHeading
        title="偏差管理"
        subtitle="QA 统一登记偏差并推进调查、评估与关闭；编号按登记月份自动生成，自发现之日起 30 天内关闭。"
        actions={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
            <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport} disabled={total === 0}>导出台账</Button>
            {canCreate && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>登记偏差</Button>
            )}
          </Space>
        }
      />

      <div style={{ ...cardStyle, background: '#ffffff', padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <button type="button" aria-pressed={statusFilter === 'all'} style={pillTabStyle(statusFilter === 'all')} onClick={() => { setStatusFilter('all'); setPage(1) }}>
            全部<span style={tabCountStyle(statusFilter === 'all')}>{totalCount}</span>
          </button>
          {STATUS_ORDER.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              style={pillTabStyle(statusFilter === status)}
              onClick={() => { setStatusFilter(status); setPage(1) }}
            >
              {DEVIATION_STATUS_LABEL[status]}<span style={tabCountStyle(statusFilter === status)}>{summary[status] ?? 0}</span>
            </button>
          ))}
          <span aria-hidden="true" style={{ width: 1, height: 20, background: '#e5e3df', margin: '0 4px' }} />
          <button
            type="button"
            aria-pressed={statusFilter === 'overdue'}
            style={pillTabStyle(statusFilter === 'overdue', true)}
            onClick={() => { setStatusFilter('overdue'); setPage(1) }}
          >
            已超期{overdueBadge !== null && <span style={tabCountStyle(statusFilter === 'overdue')}>{overdueBadge}</span>}
          </button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
          <Input.Search
            id="qa-deviation-search"
            style={{ flex: '1 1 260px', minWidth: 220, maxWidth: 340 }}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onSearch={(value) => { setQueryKeyword(value); setPage(1) }}
            allowClear
            placeholder="搜索编号、描述、部门、发现人、批号"
          />
          <Select
            id="qa-deviation-classification"
            style={{ width: 136 }}
            allowClear
            placeholder="偏差分类"
            value={classification}
            onChange={(value) => { setClassification(value); setPage(1) }}
            options={toOptions(DEVIATION_CLASSIFICATION_LABEL)}
          />
          <Select
            id="qa-deviation-root-cause"
            style={{ width: 152 }}
            allowClear
            placeholder="根本原因分类"
            value={rootCause}
            onChange={(value) => { setRootCause(value); setPage(1) }}
            options={toOptions(ROOT_CAUSE_CATEGORY_LABEL)}
          />
          <DatePicker.RangePicker
            id={{ start: 'qa-deviation-from', end: 'qa-deviation-to' }}
            style={{ width: 248 }}
            value={range}
            onChange={(value) => { setRange(value); setPage(1) }}
            placeholder={['发现日期起', '发现日期止']}
            allowClear
          />
          {filtered && rows.length > 0 && (
            <Button type="text" size="small" onClick={resetFilters} style={{ color: '#787671' }}>
              清除筛选
            </Button>
          )}
        </div>
      </div>

      <Table<DeviationBrief>
        rowKey="id"
        size="middle"
        className={styles.table}
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={screens.xl ? undefined : { x: 974 }}
        onRow={(row) => ({
          onClick: () => router.push(`/qa/deviation/${row.id}`),
          onKeyDown: (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              router.push(`/qa/deviation/${row.id}`)
            }
          },
          tabIndex: 0,
          role: 'link',
          'aria-label': `${row.deviation_no}，${DEVIATION_STATUS_LABEL[row.status]}`,
          style: { cursor: 'pointer' },
        })}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          showTotal: (count) => `共 ${count} 条`,
          onChange: (next) => setPage(next),
        }}
        style={{ ...cardStyle, background: '#ffffff', overflow: 'hidden' }}
        locale={{
          emptyText: filtered ? (
            <EmptyState
              title={statusFilter === 'overdue' ? '没有超过关闭期限的偏差' : '没有符合条件的偏差'}
              hint={statusFilter === 'overdue' ? '当前台账内的偏差都在期限内。' : '换个关键词，或清除筛选后再试。'}
              action={<Button onClick={resetFilters}>清除筛选</Button>}
            />
          ) : (
            <EmptyState
              title="还没有偏差记录"
              hint="登记第一起偏差后，这里会显示处理进度与关闭期限。"
              action={canCreate ? <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>登记偏差</Button> : undefined}
            />
          ),
        }}
      />

      <DeviationCreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
