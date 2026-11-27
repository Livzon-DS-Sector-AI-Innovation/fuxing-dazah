'use client'

// 导出记录（需求「导出行为留存记录」）：谁、什么时候、按什么条件、导了哪些字段、多少条。
// 每次导出后端都会写一条；这里只读展示，有离职台账管理权限的人才能看。

import { useEffect, useState } from 'react'
import { Alert, Drawer, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchDepartureExportLogs } from '@/actions/hr'
import type { DepartureExportLog } from '@/types/hr'

const { Text } = Typography

function fmtTime(value?: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

export default function DepartureExportLogDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [logs, setLogs] = useState<DepartureExportLog[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 抽屉打开即拉取，置 loading 是刻意的即时反馈
    setLoading(true)
    fetchDepartureExportLogs()
      .then((data) => {
        if (!cancelled) {
          setLogs(data)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载导出记录失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open])

  const columns: ColumnsType<DepartureExportLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 150,
      render: (value: string | null) => fmtTime(value),
    },
    { title: '操作人', dataIndex: 'operator_name', width: 110 },
    { title: '导出条数', dataIndex: 'row_count', width: 90, align: 'right' },
    {
      title: '筛选条件',
      key: 'filters',
      render: (_v: unknown, row) => {
        const entries = Object.entries(row.filters || {}).filter(([, value]) => value !== null && value !== '')
        if (!entries.length) return <Text type="secondary">未设条件（整表）</Text>
        return (
          <Space size={[4, 4]} wrap>
            {entries.map(([key, value]) => (
              <Tag key={key}>{`${key}：${value === true ? '是' : value === false ? '否' : String(value)}`}</Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '导出字段',
      key: 'columns',
      width: 280,
      render: (_v: unknown, row) => (
        <Space size={[4, 4]} wrap>
          {(row.columns || []).map((label) => (
            <Tag key={label} color="blue">{label}</Tag>
          ))}
        </Space>
      ),
    },
  ]

  return (
    <Drawer open={open} onClose={onClose} size={820} title="导出记录">
      {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 12 }} />}
      <Table<DepartureExportLog>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={logs || []}
        loading={loading}
        pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 条` }}
        locale={{ emptyText: '还没有导出记录' }}
      />
    </Drawer>
  )
}
