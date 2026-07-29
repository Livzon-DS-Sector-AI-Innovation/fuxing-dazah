'use client'

import { Table, Tag, Space, Button, Popconfirm } from 'antd'
import { EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'
import { NitrogenPushConfig } from '@/types/energy'
import { usePermission } from '@/hooks/usePermission'

interface NitrogenPushConfigTableProps {
  data: NitrogenPushConfig[]
  loading?: boolean
  total?: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onEdit: (record: NitrogenPushConfig) => void
  onDelete: (id: string) => void
}

export function NitrogenPushConfigTable({
  data,
  loading = false,
  total = 0,
  page,
  pageSize,
  onPageChange,
  onEdit,
  onDelete,
}: NitrogenPushConfigTableProps) {
  const { hasPermission } = usePermission()

  const columns: TableColumnsType<NitrogenPushConfig> = [
    {
      title: '配置名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '定时推送',
      dataIndex: 'notify_time',
      key: 'notify_time',
      width: 120,
      render: (v: string | null) => {
        if (!v) return <span style={{ color: '#a4a097' }}>仅手动</span>
        return <Tag color="blue">每月 {v}</Tag>
      },
    },
    {
      title: '接收人',
      dataIndex: 'notify_users',
      key: 'notify_users',
      width: 220,
      render: (users: { name: string; feishu_open_id: string }[]) => {
        if (!users || users.length === 0) return <span style={{ color: '#a4a097' }}>未设置</span>
        return (
          <Space wrap size={[4, 4]}>
            {users.slice(0, 3).map((u, i) => (
              <Tag key={i} color="blue">{u.name}</Tag>
            ))}
            {users.length > 3 && <Tag>+{users.length - 3}</Tag>}
          </Space>
        )
      },
    },
    {
      title: '氮气设备',
      dataIndex: 'nitrogen_device_names',
      key: 'nitrogen_devices',
      width: 200,
      render: (names: string[]) => {
        if (!names || names.length === 0) return <span style={{ color: '#a4a097' }}>未配置</span>
        return (
          <Space wrap size={[2, 2]}>
            {names.slice(0, 2).map((n, i) => <Tag key={i} color="purple">{n}</Tag>)}
            {names.length > 2 && <Tag>+{names.length - 2}</Tag>}
          </Space>
        )
      },
    },
    {
      title: '月度保底消费量',
      dataIndex: 'monthly_guaranteed_consumption',
      key: 'monthly_guaranteed_consumption',
      width: 150,
      render: (v: number) => {
        if (!v && v !== 0) return '—'
        return <span>{v.toLocaleString()}</span>
      },
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 80,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'success' : 'default'}>
          {enabled ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '上次推送',
      dataIndex: 'last_sent_at',
      key: 'last_sent_at',
      width: 160,
      render: (v: string | null) =>
        v ? dayjs(v).format('MM-DD HH:mm') : '—',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 130,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Space>
          {hasPermission('energy:nitrogen_report:update') && (
            <Button
              type="link"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            >
              编辑
            </Button>
          )}
          {hasPermission('energy:nitrogen_report:delete') && (
            <Popconfirm
              title="确定删除此推送配置？"
              onConfirm={() => onDelete(record.id)}
              okText="确定"
              cancelText="取消"
            >
              <Button type="link" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={data}
      loading={loading}
      rowKey="id"
      scroll={{ x: 'max-content' }}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showQuickJumper: false,
        showTotal: (total) => `共 ${total} 条`,
        onChange: (p, s) => {
          if (s !== pageSize) {
            onPageChange(1, s)
          } else {
            onPageChange(p, s)
          }
        },
      }}
    />
  )
}
