'use client'

import { useCallback, useMemo, useState } from 'react'
import { App, Button, Empty, Select, Space, Table, Tooltip } from 'antd'
import { EyeOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchMsdsCollections, fetchMsdsStats } from '@/lib/api/safety/msds'
import { retryMsdsParse } from '@/actions/safety'
import type { MsdsCollectionRecord } from '@/types/safety'
import MsdsDetailDrawer from './MsdsDetailDrawer'
import {
  CARD_STYLE,
  PARSE_STATUS_FILTER,
  PARSE_STATUS_UI,
  T,
  UI,
} from './msdsConstants'

function KpiCard({ label, value, caption, bg, valueColor }: {
  label: string; value: string; caption?: string; bg?: string; valueColor?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: valueColor ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
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
        return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
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
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="采集总数" value={String(stats?.total_collections ?? '-')} bg={T.lavender} valueColor={T.primary} caption="供应商资料上传" />
        <KpiCard label="已解析" value={String(stats?.parsed_collections ?? 0)} bg={T.mint} valueColor={T.success} caption="AI 提取完成" />
        <KpiCard label="解析失败" value={String(stats?.failed_collections ?? 0)} bg={T.rose} valueColor={T.error} caption="可手动重试" />
        <KpiCard label="台账收录" value={String(stats?.total_documents ?? '-')} bg={T.sky} valueColor="#005bab" caption="MSDS 表记录" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Select value={parseStatus} onChange={(v) => setParseStatus(v)}
            options={PARSE_STATUS_FILTER} style={{ width: 130 }} placeholder="解析状态" allowClear />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={() => setApplied({ parseStatus })} size="small" /></Tooltip>
          <span style={{ fontSize: 12, color: UI.steel }}>供应商在飞书「供应商资料」表上传原始 MSDS，平台自动解析并写回「MSDS」表</span>
        </div>

        <Table<MsdsCollectionRecord>
          columns={columns} dataSource={rows} rowKey="id"
          loading={isLoading} scroll={{ x: 900 }}
          locale={{ emptyText: <Empty description="暂无供应商资料采集" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setApplied({ parseStatus }); setPage(p); setPageSize(ps) },
          }}
          size="middle"
        />
      </div>

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
