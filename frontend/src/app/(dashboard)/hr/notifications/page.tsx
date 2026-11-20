'use client'

import PageHeader from '@/components/hr/PageHeader'
import { useEffect, useState } from 'react'
import { Card, Table, Tag, message } from 'antd'

import { fetchNotificationLogs } from '@/actions/hr'

export default function NotificationsPage() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchNotificationLogs({ page_size: 100 })
      .then(d => setLogs(d.data || []))
      .catch((err: unknown) => {
        setLogs([])
        message.error((err instanceof Error ? err.message : '') || '通知记录加载失败')
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-4">
      <PageHeader title="通知记录" description="飞书入职/离职通知发送记录" />
      <Card>
        <Table rowKey="id" loading={loading} dataSource={logs} pagination={{ pageSize: 20 }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 170, render: (v: string) => v?.replace('T', ' ').substring(0, 19) },
            { title: '员工', dataIndex: 'employee_name', width: 100 },
            { title: '通知对象', dataIndex: 'recipient', width: 100 },
            { title: '类型', dataIndex: 'email_type', width: 80, render: (v: string) => v?.includes('onboarding') ? '入职' : '离职' },
            { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'sent' ? 'green' : 'red'}>{v === 'sent' ? '已发送' : '未发送'}</Tag> },
            { title: '详情', dataIndex: 'error_message', ellipsis: true },
          ]} />
      </Card>
    </div>
  )
}
