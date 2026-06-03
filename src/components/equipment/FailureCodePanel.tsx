'use client'

import { useCallback } from 'react'
import { App, Table, Tag, Button, Space, Tabs } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { FailureCode } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteFailureCode } from '@/actions/equipment'

const tabConfig = [
  { key: 'symptoms' as const, label: '故障现象', path: 'symptoms' as const },
  { key: 'causes' as const, label: '故障原因', path: 'causes' as const },
  { key: 'actions' as const, label: '维修措施', path: 'actions' as const },
]

interface FailureCodePanelProps {
  onRefresh?: () => void
}

export function FailureCodePanel({ onRefresh }: FailureCodePanelProps) {
  const { message, modal } = App.useApp()
  const { failureCodes, failureCodeLoading, openFailureCodeDrawer } = useEquipmentStore()

  const handleDelete = useCallback((path: 'symptoms' | 'causes' | 'actions', record: FailureCode) => {
    modal.confirm({
      title: '确认删除',
      content: `确定要删除 "${record.name}" 吗？`,
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteFailureCode(path, record.id)
          message.success('删除成功')
          onRefresh?.()
        } catch (error: any) {
          message.error(error?.message || '删除失败')
        }
      },
    })
  }, [modal, message, onRefresh])

  const getColumns = (path: 'symptoms' | 'causes' | 'actions'): ColumnsType<FailureCode> => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 120 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true, render: (t: string | null) => t || '-' },
    { title: '排序', dataIndex: 'sort_order', key: 'sort_order', width: 80, align: 'center' },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 80,
      render: (active: boolean) => (
        <Tag style={{
          color: active ? '#1aae39' : '#787671',
          background: active ? '#e6f7e6' : '#f0eeec',
          border: 'none', borderRadius: 4,
        }}>{active ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: FailureCode) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openFailureCodeDrawer(path, record)} style={{ padding: 0 }}>编辑</Button>
          <Button type="link" danger icon={<DeleteOutlined />} onClick={() => handleDelete(path, record)} style={{ padding: 0 }}>删除</Button>
        </Space>
      ),
    },
  ]

  const tabItems = tabConfig.map((config) => ({
    key: config.key,
    label: config.label,
    children: (
      <div>
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openFailureCodeDrawer(config.key)}>
            新增{config.label}
          </Button>
        </div>
        <Table
          columns={getColumns(config.key)}
          dataSource={failureCodes[config.key]}
          rowKey="id"
          loading={failureCodeLoading}
          pagination={false}
          size="small"
        />
      </div>
    ),
  }))

  return <Tabs items={tabItems} />
}
