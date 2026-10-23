'use client'

/**
 * 四新域通用页面（3.0 四期 1-C）——「空态即设计」。
 *
 * 结构：PageHeader（三态 StatusTag）→ StatCard 统计行（未接入值「—」）→
 * 本域健康度口径 → 主台账分页表（列=蓝本，空表 EmptyGuide 建表接入引导）→
 * 可选副台账表（如 S6 违章档案，全量行客户端分页，副表未接入时区块隐藏）。
 * 纯只读监控，零业务操作按钮（3.0 口径：操作在飞书多维表格与机器人）；
 * 接入数据源后本组件零改码出数。差异配置见 ./domain-config.ts。
 */
import { useState } from 'react'
import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { DatabaseZap, TriangleAlert } from 'lucide-react'
import {
  fetchDomainPage,
  type DomainLedgerRow,
  type DomainPageKey,
  type DomainPageStatus,
} from '@/lib/api/safety/domain-pages'
import {
  EmptyGuide,
  PageHeader,
  SectionCard,
  StatCard,
  StatusTag,
} from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import { getDomainConfig } from './domain-config'
import type { DomainColumnConfig } from './domain-config'

const STATUS_TAG: Record<DomainPageStatus, { label: string; tone: Tone }> = {
  not_connected: { label: '未接入', tone: 'default' },
  live: { label: '已接入', tone: 'ok' },
  degraded: { label: '数据降级', tone: 'warn' },
}

/** 单元格通用格式化：null→「—」、数组→顿号连接、ISO 时间→本地日期 */
function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length > 0 ? value.join('、') : '—'
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) {
    const d = dayjs(value)
    return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : value
  }
  return String(value)
}

export default function DomainLedgerPage({ domain }: { domain: DomainPageKey }) {
  const config = getDomainConfig(domain)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const query = useQuery({
    queryKey: ['domain-page', domain, { page, pageSize }],
    queryFn: () => fetchDomainPage(domain, { page, page_size: pageSize }),
  })
  const data = query.data
  const status = data?.status
  const tag = status ? STATUS_TAG[status] : undefined

  const toColumns = (cols: DomainColumnConfig[]) =>
    cols.map((col) => ({
      title: col.title,
      dataIndex: col.dataIndex,
      width: col.width,
      render: (value: unknown) => formatCell(value),
    }))

  const columns: ColumnsType<DomainLedgerRow> = toColumns(config.columns)
  const secondaryConfig = config.secondaryLedger
  const secondaryColumns = secondaryConfig ? toColumns(secondaryConfig.columns) : null

  const emptyGuide = (() => {
    if (query.isError) {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据暂时不可用"
          description="页面数据加载失败，请稍后重试或联系管理员"
        />
      )
    }
    if (status === 'not_connected') {
      return (
        <EmptyGuide
          compact
          icon={<DatabaseZap size={28} />}
          title="数据源未接入"
          description={config.guideDescription}
          extra={
            <span style={{ fontSize: 12, color: '#a4a097' }}>
              建表字段蓝本：{config.blueprintRef}
            </span>
          }
        />
      )
    }
    if (status === 'degraded') {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据源读取降级"
          description={(data?.errors ?? []).join('；') || '连接有效但读取失败，稍后自动恢复'}
        />
      )
    }
    return (
      <EmptyGuide
        compact
        title="暂无记录"
        description={`台账在飞书多维表格维护，共 ${data?.ledger.meta.total ?? 0} 条`}
      />
    )
  })()

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', config.group]}
        title={config.title}
        description={config.description}
        extra={tag ? <StatusTag label={tag.label} tone={tag.tone} /> : undefined}
      />

      {/* 统计行（蓝本口径；未接入显示「—」） */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {config.statCards.map((card) => {
          const raw = data?.stats?.[card.key]
          const value =
            status === 'live' && raw !== null && raw !== undefined
              ? `${raw}${card.unit ?? ''}`
              : '—'
          return (
            <StatCard
              key={card.key}
              label={card.label}
              value={value}
              tone={status === 'live' && raw !== null && raw !== undefined ? card.tone : 'default'}
              sub={card.hint}
              loading={query.isLoading}
            />
          )
        })}
      </div>

      {/* 本域健康度口径（状态标签在页头，这里只放判据说明） */}
      <SectionCard
        title="本域健康度"
        description="健康度卡同步展示在总览驾驶舱健康度墙"
        className="mb-4"
      >
        <span style={{ fontSize: 13, color: '#6b675e' }}>{config.healthNote}</span>
      </SectionCard>

      {/* 主台账（列=蓝本；空态即接入引导） */}
      <SectionCard title={config.ledgerTitle} description={config.ledgerDescription}>
        <Table
          columns={columns}
          dataSource={data?.ledger.data ?? []}
          rowKey="record_id"
          size="small"
          loading={query.isLoading}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: emptyGuide }}
          pagination={{
            current: page,
            pageSize,
            total: data?.ledger.meta.total ?? 0,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage)
              setPageSize(nextPageSize)
            },
          }}
        />
      </SectionCard>

      {/* 副台账（如 S6 违章档案）：全量行客户端分页；副表未接入时区块整体隐藏 */}
      {secondaryConfig && secondaryColumns && data?.secondary_ledger && (
        <SectionCard
          title={secondaryConfig.title}
          description={secondaryConfig.description}
          className="mt-4"
        >
          <Table
            columns={secondaryColumns}
            dataSource={data.secondary_ledger.data}
            rowKey="record_id"
            size="small"
            loading={query.isLoading}
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: (
                <EmptyGuide
                  compact
                  title="暂无违章记录"
                  description="违章行为档案在飞书多维表格维护"
                />
              ),
            }}
            pagination={{
              pageSize,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
            }}
          />
        </SectionCard>
      )}
    </div>
  )
}
