'use client'

import { Table, Tag, Space, Button, Popconfirm, Switch } from 'antd'
import { EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { WorkshopConfig } from '@/types/energy'
import { usePermission } from '@/hooks/usePermission'

interface WorkshopConfigTableProps {
  data: WorkshopConfig[]
  loading?: boolean
  total?: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onEdit: (record: WorkshopConfig) => void
  onDelete: (id: string) => void
}

export function WorkshopConfigTable({
  data,
  loading = false,
  total = 0,
  page,
  pageSize,
  onPageChange,
  onEdit,
  onDelete,
}: WorkshopConfigTableProps) {
  const { hasPermission } = usePermission()

  const columns: TableColumnsType<WorkshopConfig> = [
    {
      title: '车间名称',
      dataIndex: 'workshop',
      key: 'workshop',
      width: 140,
    },
    {
      title: '负责人',
      dataIndex: 'heads',
      key: 'heads',
      width: 200,
      render: (heads: { name: string; feishu_open_id: string }[]) => {
        if (!heads || heads.length === 0) return <span style={{ color: '#a4a097' }}>未设置</span>
        return (
          <Space wrap size={[4, 4]}>
            {heads.map((h, i) => (
              <Tag key={i} color="blue">{h.name}</Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '自动通知',
      dataIndex: 'auto_notify_enabled',
      key: 'auto_notify_enabled',
      width: 100,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'success' : 'default'}>
          {enabled ? '已开启' : '已关闭'}
        </Tag>
      ),
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
      title: '上次检查',
      dataIndex: 'last_checked_at',
      key: 'last_checked_at',
      width: 180,
      render: (v: string | null) => v || '—',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Space>
          {hasPermission('energy:workshop_config:update') && (
            <Button
              type="link"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            >
              编辑
            </Button>
          )}
          {hasPermission('energy:workshop_config:delete') && (
            <Popconfirm
              title="确定删除此车间配置？"
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
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showQuickJumper: true,
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
