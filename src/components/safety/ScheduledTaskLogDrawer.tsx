'use client'

import { Descriptions, Drawer, Table, Tag, Timeline, Typography } from 'antd'
import { useEffect, useState } from 'react'
import type { ScheduledTaskLog } from '@/types/safety'
import { getScheduledTaskLogs } from '@/actions/safety'

const { Text, Paragraph } = Typography

interface ScheduledTaskLogDrawerProps {
  open: boolean
  taskId: string
  taskName: string
  onClose: () => void
}

const statusColors: Record<string, string> = {
  running: 'processing',
  success: 'success',
  failure: 'error',
}

export default function ScheduledTaskLogDrawer({
  open,
  taskId,
  taskName,
  onClose,
}: ScheduledTaskLogDrawerProps) {
  const [logs, setLogs] = useState<ScheduledTaskLog[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open && taskId) {
      setLoading(true)
      getScheduledTaskLogs(taskId)
        .then((res) => {
          if (res.code === 200 && res.data) {
            setLogs(res.data)
          }
        })
        .catch(() => {
          // ignore
        })
        .finally(() => setLoading(false))
    }
  }, [open, taskId])

  const columns = [
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => <Tag color={statusColors[s] || 'default'}>{s === 'success' ? '成功' : s === 'failure' ? '失败' : '运行中'}</Tag>,
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 80,
      render: (v: number | null) => (v != null ? `${v}ms` : '-'),
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (v: string | null) => v ? <Text type="danger">{v}</Text> : '-',
    },
  ]

  return (
    <Drawer
      title={`执行日志 - ${taskName}`}
      open={open}
      onClose={onClose}
      width={700}
    >
      <Table
        dataSource={logs}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
        expandable={{
          expandedRowRender: (record) => (
            <div style={{ padding: 8 }}>
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="完成时间">
                  {record.completed_at ? new Date(record.completed_at).toLocaleString('zh-CN') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="飞书消息ID">{record.feishu_msg_id || '-'}</Descriptions.Item>
                {record.data_snapshot && (
                  <Descriptions.Item label="数据快照">
                    <Paragraph
                      code
                      ellipsis={{ rows: 5, expandable: true }}
                      style={{ fontSize: 11 }}
                    >
                      {JSON.stringify(record.data_snapshot, null, 2)}
                    </Paragraph>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </div>
          ),
        }}
      />
    </Drawer>
  )
}
