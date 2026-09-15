'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Space, Button, App, Segmented, Popconfirm } from 'antd'
import { CheckOutlined, UndoOutlined, DownloadOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import type { UnqualifiedEvent } from '@/types/quality'
import { fetchUnqualifiedEvents, markUnqualifiedEventHandled, exportUnqualifiedEvents } from '@/actions/quality'

const SOURCE_LABEL: Record<string, string> = {
  manual: '机器人填报',
  web: '网页端',
  parse: '液相解析',
}

export default function UnqualifiedEvents() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canReview = hasPermission('quality:task:review')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<UnqualifiedEvent[]>([])
  const [filter, setFilter] = useState<'all' | 'open' | 'done'>('open')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const handled = filter === 'all' ? undefined : filter === 'done'
      const res = await fetchUnqualifiedEvents(handled)
      setData(res.data || [])
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [filter, message])

  useEffect(() => { load() }, [load])

  const handleToggle = async (e: UnqualifiedEvent) => {
    try {
      await markUnqualifiedEventHandled(e.id, !e.handled)
      message.success(e.handled ? '已取消标记' : '已标记处理')
      load()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const columns = [
    {
      title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 180, ellipsis: true },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 130 },
    { title: 'SOP号', dataIndex: 'sop_no', key: 'sop_no', width: 120, render: (v: string | null) => v || '-' },
    { title: '项目', dataIndex: 'item_name', key: 'item_name', width: 130 },
    {
      title: '实测值', dataIndex: 'result_value', key: 'result_value', width: 100,
      render: (v: number | null) => v != null ? String(v) : '-',
    },
    { title: '限度', dataIndex: 'limit_text', key: 'limit_text', width: 130, render: (v: string | null) => v || '-' },
    {
      title: '来源', dataIndex: 'source', key: 'source', width: 100,
      render: (v: string) => <Tag>{SOURCE_LABEL[v] || v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'handled', key: 'handled', width: 90,
      render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '已处理' : '待处理'}</Tag>,
    },
    ...(canReview ? [{
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: UnqualifiedEvent) => (
        <Popconfirm
          title={r.handled ? '取消处理标记？' : '确认已人工处理？'}
          onConfirm={() => handleToggle(r)}
        >
          <Button size="small" type={r.handled ? 'default' : 'primary'} icon={r.handled ? <UndoOutlined /> : <CheckOutlined />}>
            {r.handled ? '取消' : '处理'}
          </Button>
        </Popconfirm>
      ),
    }] : []),
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as typeof filter)}
          options={[
            { label: '待处理', value: 'open' },
            { label: '已处理', value: 'done' },
            { label: '全部', value: 'all' },
          ]}
        />
        <Button icon={<DownloadOutlined />} onClick={async () => {
          try {
            const blob = await exportUnqualifiedEvents(filter === 'all' ? undefined : filter === 'done')
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = '不合格台账.csv'
            a.click()
            URL.revokeObjectURL(url)
          } catch (err: any) {
            message.error(err.message || '导出失败')
          }
        }}>导出 CSV</Button>
      </Space>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        size="small"
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 1200 }}
      />
    </div>
  )
}
