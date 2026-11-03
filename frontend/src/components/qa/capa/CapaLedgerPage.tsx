'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { App, Button, Input, Select, Space, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeading } from '@/components/shared/PageHeading'
import { fetchCapaSummary, fetchCapas } from '@/lib/api/qa-deviation'
import {
  CAPA_SEVERITY_LABEL,
  CAPA_STATUS_LABEL,
  EFFECT_CONCLUSION_LABEL,
  type CapaBrief,
  type CapaSeverity,
  type CapaStatus,
} from '@/types/qa-deviation'
import { CapaStatusPill, PILL, SeverityPill, cardStyle, fmtDate, toOptions } from '../deviation/shared'
import { CapaDetailDrawer } from './CapaDetailDrawer'

const PAGE_SIZE = 20
const STATUS_ORDER: CapaStatus[] = ['planned', 'in_progress', 'completed', 'effect_evaluating', 'closed']

const pillTabStyle = (active: boolean): CSSProperties => ({
  padding: '4px 14px',
  fontSize: 13,
  fontWeight: 500,
  lineHeight: '22px',
  color: active ? '#ffffff' : '#787671',
  background: active ? '#000000' : 'transparent',
  border: active ? '1px solid #000000' : '1px solid #e5e3df',
  borderRadius: 9999,
  cursor: 'pointer',
  fontFamily: 'inherit',
})

export function CapaLedgerPage() {
  const { message } = App.useApp()
  const router = useRouter()
  const searchParams = useSearchParams()

  const [keyword, setKeyword] = useState('')
  const [queryKeyword, setQueryKeyword] = useState('')
  const [status, setStatus] = useState<CapaStatus | 'all'>('all')
  const [severity, setSeverity] = useState<CapaSeverity | undefined>()
  const [page, setPage] = useState(1)
  // 从偏差详情跳转过来时带 ?id= 直接打开对应 CAPA。
  const [openId, setOpenId] = useState<string | null>(() => searchParams.get('id'))
  const queryClient = useQueryClient()

  const listParams = useMemo(
    () => ({
      keyword: queryKeyword.trim() || undefined,
      status: status === 'all' ? undefined : status,
      severity,
    }),
    [queryKeyword, severity, status],
  )

  const listQuery = useQuery({
    queryKey: ['qa', 'capas', listParams, page],
    queryFn: () => fetchCapas({ ...listParams, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const summaryQuery = useQuery({
    queryKey: ['qa', 'capas', 'summary'],
    queryFn: fetchCapaSummary,
  })
  const { isError } = listQuery
  useEffect(() => {
    if (isError) message.error('加载 CAPA 台账失败')
  }, [isError, message])

  const rows = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const loading = listQuery.isFetching
  const summary: Partial<Record<CapaStatus, number>> = summaryQuery.data ?? {}
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['qa', 'capas'] })

  const closeDrawer = () => {
    setOpenId(null)
    if (searchParams.get('id')) router.replace('/qa/capa')
  }

  const columns: ColumnsType<CapaBrief> = [
    {
      title: 'CAPA 编号',
      dataIndex: 'capa_no',
      width: 190,
      render: (value: string, row) => (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
          <span style={{ color: '#0075de', fontWeight: 600 }}>{value}</span>
          <Space size={4}>
            {row.is_overdue && <span style={PILL.error}>计划逾期</span>}
            {row.effect_conclusion === 'ineffective' && <span style={PILL.error}>评估无效</span>}
            {row.parent_capa_id && <span style={PILL.purple}>追加</span>}
          </Space>
        </div>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 120, render: (value: CapaStatus) => <CapaStatusPill status={value} /> },
    { title: '严重性', dataIndex: 'severity', width: 80, render: (value: CapaSeverity) => <SeverityPill value={value} /> },
    {
      title: '来源偏差',
      dataIndex: 'deviation_no',
      width: 120,
      render: (value: string | null, row) => value ? (
        <Link href={`/qa/deviation/${row.deviation_id}`} onClick={(event) => event.stopPropagation()} style={{ color: '#0075de' }}>{value}</Link>
      ) : '—',
    },
    {
      title: '问题及 CAPA 要求',
      dataIndex: 'summary',
      ellipsis: { showTitle: false },
      render: (value: string) => <Tooltip title={value} placement="topLeft"><span>{value}</span></Tooltip>,
    },
    { title: '责任部门', dataIndex: 'responsible_department_name', width: 120, render: (value: string | null) => value || '—' },
    {
      title: '计划完成',
      dataIndex: 'planned_completion_date',
      width: 110,
      render: (value: string | null, row) => <span style={{ color: row.is_overdue ? '#e03131' : undefined }}>{fmtDate(value)}</span>,
    },
    { title: '有效性评估到期', dataIndex: 'effect_due_date', width: 130, render: (value: string | null) => fmtDate(value) },
    {
      title: '结论',
      dataIndex: 'effect_conclusion',
      width: 80,
      render: (value: CapaBrief['effect_conclusion']) => value ? EFFECT_CONCLUSION_LABEL[value] : '—',
    },
  ]

  const totalCount = STATUS_ORDER.reduce((sum, item) => sum + (summary[item] ?? 0), 0)

  return (
    <div style={{ maxWidth: 1480, margin: '0 auto', paddingBottom: 36 }}>
      <PageHeading
        title="CAPA 管理"
        subtitle="纠正与预防措施台账：从偏差评估发起，跟踪措施实施与有效性评估，结论有效后由 QA 关闭。"
        actions={<Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>}
      />

      <div style={{ ...cardStyle, background: '#ffffff', padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
          <button type="button" aria-pressed={status === 'all'} style={pillTabStyle(status === 'all')} onClick={() => { setStatus('all'); setPage(1) }}>
            全部 {totalCount}
          </button>
          {STATUS_ORDER.map((item) => (
            <button key={item} type="button" aria-pressed={status === item} style={pillTabStyle(status === item)} onClick={() => { setStatus(item); setPage(1) }}>
              {CAPA_STATUS_LABEL[item]} {summary[item] ?? 0}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <Input.Search
            id="qa-capa-search"
            style={{ width: 320 }}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onSearch={(value) => { setQueryKeyword(value); setPage(1) }}
            allowClear
            placeholder="搜索 CAPA 编号、概述、责任部门"
          />
          <Select
            style={{ width: 140 }}
            allowClear
            placeholder="严重性"
            value={severity}
            onChange={(value) => { setSeverity(value); setPage(1) }}
            options={toOptions(CAPA_SEVERITY_LABEL)}
          />
        </div>
      </div>

      <Table<CapaBrief>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        onRow={(row) => ({
          onClick: () => setOpenId(row.id),
          onKeyDown: (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              setOpenId(row.id)
            }
          },
          tabIndex: 0,
          role: 'link',
          'aria-label': `${row.capa_no}，${CAPA_STATUS_LABEL[row.status]}`,
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
        locale={{ emptyText: '尚无 CAPA；在偏差详情的评估区块中发起' }}
      />

      <CapaDetailDrawer capaId={openId} onClose={closeDrawer} onChanged={refresh} />
    </div>
  )
}
