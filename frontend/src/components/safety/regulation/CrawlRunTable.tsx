'use client'

/** 运行历史分页表 + 运行详情 Drawer（ragplus 采集段快照 + 本仓收录段逐条管线）。 */

import { useState } from 'react'
import { Drawer, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { EmptyGuide, StatusTag } from '@/components/ui-kit'
import { fetchRegulationRunDetail } from '@/lib/api/safety/regulation-monitor'
import { formatMonitorTimeFull } from './format'
import type { RegulationIngestRunRow } from '@/types/safety'

const RUN_STATUS: Record<string, { label: string; tone: 'ok' | 'warn' | 'danger' }> = {
  completed: { label: '完成', tone: 'ok' },
  skipped_disabled: { label: '总闸跳过', tone: 'warn' },
  failed: { label: '失败', tone: 'danger' },
}

const ACTION_TAG: Record<string, string> = {
  promote: 'green',
  reject: 'default',
  duplicate: 'default',
  pending: 'gold',
  error: 'red',
}

export default function CrawlRunTable({
  runs,
  total,
  page,
  pageSize,
  onPageChange,
}: {
  runs: RegulationIngestRunRow[]
  total: number
  page: number
  pageSize: number
  onPageChange: (p: number) => void
}) {
  const [detailRunId, setDetailRunId] = useState<string | null>(null)

  const columns: ColumnsType<RegulationIngestRunRow> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (v: string | null) => formatMonitorTimeFull(v),
    },
    {
      title: '触发',
      dataIndex: 'source',
      key: 'source',
      width: 90,
      render: (v: string) => (v === 'reconcile' ? '对账补投' : '推送'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const meta = RUN_STATUS[v] ?? { label: v, tone: 'warn' as const }
        return <StatusTag tone={meta.tone} label={meta.label} />
      },
    },
    { title: '候选', dataIndex: 'received_count', key: 'received_count', width: 70, align: 'right' },
    { title: '去重', dataIndex: 'duplicate_count', key: 'duplicate_count', width: 70, align: 'right' },
    { title: '复核', dataIndex: 'pending_count', key: 'pending_count', width: 70, align: 'right' },
    { title: '收录', dataIndex: 'promoted_count', key: 'promoted_count', width: 70, align: 'right' },
    { title: '驳回', dataIndex: 'rejected_count', key: 'rejected_count', width: 70, align: 'right' },
    { title: '失败', dataIndex: 'failed_count', key: 'failed_count', width: 70, align: 'right' },
    { title: 'AI token', dataIndex: 'ai_tokens_used', key: 'ai_tokens_used', width: 90, align: 'right' },
    {
      title: '错误摘要',
      dataIndex: 'error_summary',
      key: 'error_summary',
      ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
  ]

  if (!runs.length) {
    return <EmptyGuide compact title="暂无运行" description="收录批次留痕将在此展示" />
  }

  return (
    <>
      <Table<RegulationIngestRunRow>
        size="small"
        rowKey="run_log_id"
        columns={columns}
        dataSource={runs}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          onChange: onPageChange,
        }}
        onRow={(record) => ({
          onClick: () => setDetailRunId(record.source_run_id),
          style: { cursor: 'pointer' },
        })}
      />
      <RunDetailDrawer runId={detailRunId} onClose={() => setDetailRunId(null)} />
    </>
  )
}

function RunDetailDrawer({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['regulation-run-detail', runId],
    queryFn: () => fetchRegulationRunDetail(runId as string),
    enabled: !!runId,
  })

  const detail = query.data
  const rag = detail?.ragplus_run

  return (
    <Drawer
      title={`运行详情 · ${runId ?? ''}`}
      placement="right"
      width={560}
      open={runId !== null}
      onClose={onClose}
    >
      {query.isLoading && <div style={{ color: 'var(--color-steel)' }}>加载中…</div>}
      {query.isError && <div style={{ color: '#e03131' }}>详情拉取失败：{(query.error as Error)?.message}</div>}
      {detail && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, fontSize: 13 }}>
          {detail.errors.length > 0 && (
            <div style={{ color: '#a8071a' }}>{detail.errors.join('；')}</div>
          )}

          <section>
            <h4 style={{ marginBottom: 8 }}>采集段（ragplus 快照）</h4>
            {rag ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(rag)
                  .filter(([, v]) => v != null)
                  .map(([k, v]) => (
                    <Tag key={k}>
                      {k}: {String(v)}
                    </Tag>
                  ))}
              </div>
            ) : (
              <div style={{ color: 'var(--color-steel)' }}>无采集段快照（ragplus 未透出或拉取失败）</div>
            )}
          </section>

          <section>
            <h4 style={{ marginBottom: 8 }}>
              收录段 · 逐条管线（{detail.ingest.items_result.length} 条）
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detail.ingest.items_result.map((item) => (
                <div
                  key={item.candidate_id}
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    border: '1px solid var(--color-hairline, #eee)',
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Tag color={ACTION_TAG[item.action_taken] ?? 'default'}>{item.action_taken}</Tag>
                    <span className="truncate" style={{ fontWeight: 500 }}>{item.title ?? item.candidate_id}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--color-steel)', marginTop: 4 }}>
                    {item.reason}
                    {item.url && (
                      <>
                        {' · '}
                        <a href={item.url} target="_blank" rel="noreferrer">原文</a>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </Drawer>
  )
}
