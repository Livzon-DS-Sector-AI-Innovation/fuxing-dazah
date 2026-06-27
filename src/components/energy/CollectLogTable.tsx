'use client'

import { Table, Tag, Button, Space } from 'antd'
import { ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { CollectLog, CollectStatus } from '@/types/energy'
import { useEnergyStore } from '@/stores/energy'
import { usePermission } from '@/hooks/usePermission'

// ── 轻奢 Pill 样式 ──

const luxuryPill = (color: string, bg: string) =>
  ({
    display: 'inline-flex',
    alignItems: 'center',
    padding: '2px 12px',
    borderRadius: 9999,
    fontSize: 12,
    fontWeight: 500,
    lineHeight: '20px',
    color,
    background: bg,
  } as const)

const statusConfig: Record<CollectStatus, ReturnType<typeof luxuryPill>> = {
  success: luxuryPill('#1aae39', '#d9f3e1'),
  partial: luxuryPill('#dd5b00', '#ffe8d4'),
  failed: luxuryPill('#e03131', '#fde0ec'),
}

// ── 表格样式注入 ──

const tableStyles = `
.luxury-collect-table .ant-table-thead > tr > th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #a4a097;
  background: #fafaf9;
  border-bottom: 1px solid #ede9e4;
  padding: 10px 16px;
  font-weight: 600;
}
.luxury-collect-table .ant-table-thead > tr > th::before {
  display: none;
}
.luxury-collect-table .ant-table-tbody > tr > td {
  border-bottom: 1px solid #ede9e4;
  border-inline-end: none;
  padding: 12px 16px;
  font-size: 14px;
  color: #37352f;
}
.luxury-collect-table .ant-table-tbody > tr > td:last-child {
  border-inline-end: none;
}
.luxury-collect-table .ant-table-tbody > tr:hover > td {
  background: #f6f3ff !important;
}
.luxury-collect-table .ant-table-tbody > tr:hover > td:first-child {
  box-shadow: inset 2px 0 0 #5645d4;
}
.luxury-collect-table .ant-table {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
.luxury-collect-table .ant-table-container {
  border-inline-start: none !important;
  border-inline-end: none !important;
}
.luxury-collect-table .ant-pagination-item {
  border: none;
  background: transparent;
  font-size: 13px;
  color: #787671;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
  border-radius: 8px;
}
.luxury-collect-table .ant-pagination-item:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-collect-table .ant-pagination-item-active {
  background: #f6f3ff;
  color: #5645d4;
  font-weight: 600;
}
.luxury-collect-table .ant-pagination-item-active:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-collect-table .ant-pagination-prev,
.luxury-collect-table .ant-pagination-next {
  border: none;
  background: transparent;
  color: #787671;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
  border-radius: 8px;
}
.luxury-collect-table .ant-pagination-prev:hover,
.luxury-collect-table .ant-pagination-next:hover {
  background: #f6f3ff;
  color: #5645d4;
}
.luxury-collect-table .ant-pagination-total-text {
  font-size: 13px;
  color: #a4a097;
}
.luxury-collect-table .ant-select-selector {
  border-radius: 8px !important;
}
.luxury-collect-table .ant-spin-container::after {
  background: transparent;
}
`

// ── Props ──

interface CollectLogTableProps {
  data: CollectLog[]
  loading?: boolean
  total?: number
  onRefresh: () => void
  onRetry?: (platformCode: string) => void
}

export function CollectLogTable({
  data,
  loading = false,
  total = 0,
  onRefresh,
  onRetry,
}: CollectLogTableProps) {
  const { logFilters, setLogFilters, openCollectLogDrawer } = useEnergyStore()
  const { hasPermission } = usePermission()

  const columns: TableColumnsType<CollectLog> = [
    {
      title: '平台编码',
      dataIndex: 'platform_code',
      key: 'platform_code',
      width: 130,
      render: (code: string) => (
        <span
          style={{
            fontFamily: 'SF Mono, ui-monospace, monospace',
            fontSize: 13,
            color: '#5d5b54',
          }}
        >
          {code}
        </span>
      ),
    },
    {
      title: '采集时间',
      dataIndex: 'collect_time',
      key: 'collect_time',
      width: 180,
      render: (text: string) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', color: '#5d5b54' }}>
          {new Date(text).toLocaleString('zh-CN')}
        </span>
      ),
    },
    {
      title: '采集状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: CollectStatus) => {
        const style = statusConfig[s]
        const label =
          s === 'success' ? '成功' : s === 'partial' ? '部分成功' : '失败'
        return <span style={style}>{label}</span>
      },
    },
    {
      title: '应采 / 成功',
      key: 'count',
      width: 110,
      align: 'right',
      render: (_: unknown, record: CollectLog) => (
        <span style={{ fontVariantNumeric: 'tabular-nums', color: '#5d5b54' }}>
          <span
            style={{
              color:
                record.success_count === record.device_count
                  ? '#1aae39'
                  : record.success_count === 0
                    ? '#e03131'
                    : '#dd5b00',
            }}
          >
            {record.success_count}
          </span>
          {' / '}
          {record.device_count}
        </span>
      ),
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      width: 220,
      ellipsis: true,
      render: (text: string | null) =>
        text ? (
          <span style={{ color: '#e03131', fontSize: 13 }}>{text}</span>
        ) : (
          <span style={{ color: '#a4a097' }}>—</span>
        ),
    },
    {
      title: '',
      key: 'action',
      width: 96,
      render: (_: unknown, record: CollectLog) => (
        <div style={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => openCollectLogDrawer(record.id)}
            style={{ color: '#5645d4' }}
            aria-label="详情"
          >
            详情
          </Button>
          {record.status === 'failed' && onRetry && hasPermission('energy:collect_log:read') && (
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => onRetry(record.platform_code)}
              style={{ color: '#dd5b00' }}
              aria-label="重试"
            />
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <style>{tableStyles}</style>
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #ede9e4',
          boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)',
          overflow: 'hidden',
        }}
      >
        <Table<CollectLog>
          className="luxury-collect-table"
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 'max-content' }}
          showSorterTooltip={false}
          pagination={{
            current: logFilters.page || 1,
            pageSize: logFilters.page_size || 10,
            total,
            showSizeChanger: true,
            showQuickJumper: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => {
              setLogFilters({ page, page_size: pageSize })
            },
          }}
        />
      </div>
    </>
  )
}
