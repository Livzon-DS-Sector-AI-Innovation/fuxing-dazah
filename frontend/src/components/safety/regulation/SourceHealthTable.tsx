'use client'

/** 数据源健康表：契约③ sources 透传 + 状态 Tag + 行点开源详情 Drawer（只读）。 */

import { useState } from 'react'
import { Drawer, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EmptyGuide, StatusTag } from '@/components/ui-kit'
import { formatMonitorTimeFull } from './format'
import type { RegulationCrawlSource } from '@/types/safety'

const SOURCE_STATUS: Record<string, { label: string; tone: 'ok' | 'warn' | 'danger' | 'default' }> = {
  ok: { label: '正常', tone: 'ok' },
  warn: { label: '预警', tone: 'warn' },
  down: { label: '停摆', tone: 'danger' },
  suspect_rebuild: { label: '待重建', tone: 'warn' },
}

const LAYER_LABEL: Record<string, string> = {
  api: 'API 直连',
  http_parse: '列表解析',
  browser: '浏览器渲染',
}

export default function SourceHealthTable({ sources }: { sources: RegulationCrawlSource[] }) {
  const [detail, setDetail] = useState<RegulationCrawlSource | null>(null)

  const columns: ColumnsType<RegulationCrawlSource> = [
    { title: '数据源', dataIndex: 'name', key: 'name' },
    {
      title: '策略层',
      dataIndex: 'layer',
      key: 'layer',
      width: 110,
      render: (v?: string) => (v ? LAYER_LABEL[v] ?? v : '—'),
    },
    {
      title: '最近成功',
      dataIndex: 'last_success_at',
      key: 'last_success_at',
      width: 150,
      render: (v?: string | null) => formatMonitorTimeFull(v),
    },
    {
      title: '连续失败',
      dataIndex: 'consecutive_failures',
      key: 'consecutive_failures',
      width: 90,
      render: (v?: number) => (v ? <span style={{ color: v >= 3 ? '#e03131' : undefined }}>{v}</span> : 0),
    },
    { title: '近7日条数', dataIndex: 'items_7d', key: 'items_7d', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v?: string) => {
        const meta = SOURCE_STATUS[String(v ?? '')] ?? { label: v ?? '—', tone: 'default' as const }
        return <StatusTag tone={meta.tone} label={meta.label} />
      },
    },
  ]

  if (!sources.length) {
    return (
      <EmptyGuide
        compact
        title="暂无数据源"
        description="ragplus 契约③未返回源健康数据"
      />
    )
  }

  return (
    <>
      <Table<RegulationCrawlSource>
        size="small"
        rowKey="name"
        columns={columns}
        dataSource={sources}
        pagination={false}
        onRow={(record) => ({
          onClick: () => setDetail(record),
          style: { cursor: 'pointer' },
        })}
      />
      <Drawer
        title={`数据源详情 · ${detail?.name ?? ''}`}
        placement="right"
        width={420}
        open={detail !== null}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
            <DetailRow label="策略层" value={detail.layer ? LAYER_LABEL[detail.layer] ?? detail.layer : '—'} />
            <DetailRow label="最近成功" value={formatMonitorTimeFull(detail.last_success_at)} />
            <DetailRow label="连续失败" value={String(detail.consecutive_failures ?? 0)} />
            <DetailRow label="近7日条数" value={String(detail.items_7d ?? '—')} />
            <DetailRow
              label="状态"
              value={SOURCE_STATUS[String(detail.status ?? '')]?.label ?? detail.status ?? '—'}
            />
          </div>
        )}
      </Drawer>
    </>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--color-hairline, #eee)', paddingBottom: 6 }}>
      <span style={{ color: 'var(--color-steel, #8a8a8a)' }}>{label}</span>
      <span>{value}</span>
    </div>
  )
}
