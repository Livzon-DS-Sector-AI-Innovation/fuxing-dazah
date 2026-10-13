'use client'

// MSDS 供应商资料采集 Panel（MsdsCollectionPanel）— 对标 CertWarningPanel 形态
// StatCard 统计行（与台账共享 msds-stats 端点）→ SectionCard 采集台账（筛选 + Table + 手动触发解析）。

import { useCallback, useMemo, useState } from 'react'
import { App, Button, Select, Space, Table, Tooltip } from 'antd'
import { EyeOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchMsdsCollections, fetchMsdsStats } from '@/lib/api/safety/msds'
import { retryMsdsParse } from '@/actions/safety'
import type { MsdsCollectionRecord } from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import MsdsDetailDrawer from './MsdsDetailDrawer'
import {
  PARSE_STATUS_FILTER,
  PARSE_STATUS_UI,
  T,
  UI,
} from './msdsConstants'

/** 解析状态 → ui-kit 语义 tone */
const PARSE_STATUS_TONE: Record<string, Tone> = {
  pending: 'default',
  parsed: 'ok',
  failed: 'danger',
}

export default function MsdsCollectionPanel() {
  const { message } = App.useApp()

  const [parseStatus, setParseStatus] = useState('')
  const [applied, setApplied] = useState<{ parseStatus: string }>({ parseStatus: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [parsingId, setParsingId] = useState<string | null>(null)
  const [detailRec, setDetailRec] = useState<MsdsCollectionRecord | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const queryClient = useQueryClient()

  // 统计 query（与 MsdsPanel 共享 msds-stats 缓存）
  const statsQuery = useQuery({
    queryKey: ['msds-stats'],
    queryFn: fetchMsdsStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['msds-collections', { page, pageSize, parseStatus: applied.parseStatus }],
    queryFn: () => fetchMsdsCollections({
      page, page_size: pageSize,
      parse_status: applied.parseStatus || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleRetry = useCallback(async (rec: MsdsCollectionRecord) => {
    setParsingId(rec.id)
    try {
      const res = await retryMsdsParse(rec.id)
      if (res.code === 200) {
        message.success('解析已触发，稍后刷新查看结果')
        queryClient.invalidateQueries({ queryKey: ['msds-collections'] })
        queryClient.invalidateQueries({ queryKey: ['msds-stats'] })
      } else {
        message.error(res.message || '解析触发失败')
      }
    } catch { message.error('解析触发失败') }
    finally { setParsingId(null) }
  }, [message, queryClient])

  const columns: ColumnsType<MsdsCollectionRecord> = useMemo(() => [
    {
      title: '附件', key: 'attachment', width: 220, ellipsis: true,
      render: (_: unknown, record: MsdsCollectionRecord) => {
        const names = record.attachment?.map((a) => a.name).filter(Boolean) ?? []
        return (
          <a onClick={() => { setDetailRec(record); setDetailOpen(true) }}
             style={{ cursor: 'pointer', fontWeight: 500, color: UI.ink }}>
            {names[0] || '(未上传附件)'}
          </a>
        )
      },
    },
    {
      title: '解析状态', dataIndex: 'parse_status', key: 'parse_status', width: 110,
      render: (s: string) => {
        const ui = PARSE_STATUS_UI[s]
        if (!ui) return s || '-'
        return <StatusTag tone={PARSE_STATUS_TONE[s] ?? 'default'} label={ui.label} />
      },
    },
    {
      title: '化学品数', key: 'entry_count', width: 90,
      render: (_: unknown, record: MsdsCollectionRecord) =>
        record.parse_status === 'parsed' ? String(record.parse_result?.length ?? 0) : '-',
    },
    {
      title: '收录记录', key: 'registry_count', width: 90,
      render: (_: unknown, record: MsdsCollectionRecord) =>
        String(record.msds_table_record_ids?.length ?? 0) || '-',
    },
    {
      title: '上传日期', dataIndex: 'source_date', key: 'source_date', width: 110,
      render: (d: string) => (d ? dayjs(d).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '操作', key: 'actions', width: 130, fixed: 'right',
      render: (_: unknown, record: MsdsCollectionRecord) => (
        <Space size={4}>
          <Tooltip title="触发/重试 AI 解析（自动写回 MSDS 表）">
            <Button size="small" type="primary" icon={<ThunderboltOutlined />}
              loading={parsingId === record.id}
              onClick={() => handleRetry(record)}
              style={{ background: T.primary, borderColor: T.primary, fontSize: 12 }}>
              解析
            </Button>
          </Tooltip>
          <Button size="small" type="text" icon={<EyeOutlined />}
            onClick={() => { setDetailRec(record); setDetailOpen(true) }} />
        </Space>
      ),
    },
  ], [parsingId, handleRetry])

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（与台账共享 msds-stats 端点） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="采集总数" value={stats?.total_collections ?? '-'} sub="供应商资料上传" />
        <StatCard label="已解析" value={stats?.parsed_collections ?? 0} sub="AI 提取完成" />
        <StatCard label="解析失败" value={stats?.failed_collections ?? 0} sub="可手动重试" />
        <StatCard label="台账收录" value={stats?.total_documents ?? '-'} sub="MSDS 表记录" />
      </div>

      <SectionCard
        title="供应商资料采集"
        description="供应商在飞书「供应商资料」表上传原始 MSDS，平台自动解析并写回「MSDS」表"
      >
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Select value={parseStatus} onChange={(v) => setParseStatus(v)}
            options={PARSE_STATUS_FILTER} style={{ width: 130 }} placeholder="解析状态" allowClear />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={() => setApplied({ parseStatus })} size="small" /></Tooltip>
        </div>

        <Table<MsdsCollectionRecord>
          columns={columns} dataSource={rows} rowKey="id"
          loading={isLoading} scroll={{ x: 900 }}
          locale={{ emptyText: <EmptyGuide compact title="暂无供应商资料采集" description="供应商在飞书上传原始 MSDS 后自动同步" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setApplied({ parseStatus }); setPage(p); setPageSize(ps) },
          }}
          size="middle"
        />
      </SectionCard>

      <MsdsDetailDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detailRec?.attachment?.[0]?.name ?? '采集详情'}
        entry={detailRec?.parse_status === 'parsed' ? detailRec.parse_result?.[0] : null}
        footer={detailRec?.parse_status === 'parsed' && (detailRec.parse_result?.length ?? 0) > 1
          ? <span style={{ fontSize: 12, color: UI.steel }}>共 {detailRec.parse_result?.length} 个化学品，此处展示第 1 个</span>
          : undefined}
      />
    </div>
  )
}
