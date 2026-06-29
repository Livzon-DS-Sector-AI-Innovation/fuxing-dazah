'use client'

import { useRouter } from 'next/navigation'
import { Button, Space, Table, Tag, App } from 'antd'
import { EyeOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { deleteWorkflowDefinition } from '@/actions/workflow'
import type { WorkflowDefResponse } from '@/types/safety'

interface Props {
  items: WorkflowDefResponse[]
  total: number
}

export function WorkflowList({ items, total }: Props) {
  const router = useRouter()
  const { message } = App.useApp()

  const handleDelete = async (id: string, name: string) => {
    try {
      await deleteWorkflowDefinition(id)
      message.success(`已删除: ${name}`)
      router.refresh()
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: WorkflowDefResponse) => (
        <a onClick={() => router.push(`/safety/workflow/${record.id}`)}>{name}</a>
      ),
    },
    {
      title: '模块代码',
      dataIndex: 'module_code',
      key: 'module_code',
      width: 200,
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 80,
      render: (enabled: boolean) =>
        enabled ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (d: string) => new Date(d).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, record: WorkflowDefResponse) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => router.push(`/safety/workflow/${record.id}`)}
          >
            编辑
          </Button>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id, record.name)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={items}
      rowKey="id"
      pagination={{
        defaultPageSize: 20,
        total,
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
      }}
    />
  )
}
