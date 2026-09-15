'use client'

import { Table } from 'antd'
import type { TableColumnsType } from 'antd'

/**
 * 统一数据表（仓储 V2.0 三件套之二）：
 * 固化 size=small、服务端分页配置（showSizeChanger/共 N 条）、横向滚动，
 * 避免各页复制分页配置。
 */
export function DataTable<T extends { id: string }>({
  columns,
  dataSource,
  loading,
  total,
  page,
  pageSize,
  onPageChange,
  scrollX,
  emptyText,
  onRow,
}: {
  columns: TableColumnsType<T>
  dataSource: T[]
  loading?: boolean
  total?: number
  page?: number
  pageSize?: number
  onPageChange?: (page: number, pageSize: number) => void
  scrollX?: number
  emptyText?: string
  onRow?: (record: T) => React.HTMLAttributes<HTMLTableRowElement>
}) {
  const showPagination = total !== undefined && page !== undefined && pageSize !== undefined
  return (
    <Table<T>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={dataSource}
      loading={loading}
      locale={emptyText ? { emptyText } : undefined}
      onRow={onRow}
      pagination={
        showPagination
          ? {
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              showTotal: t => `共 ${t} 条`,
              onChange: (p, ps) => onPageChange?.(p, ps),
            }
          : false
      }
      scroll={scrollX ? { x: scrollX } : undefined}
    />
  )
}
