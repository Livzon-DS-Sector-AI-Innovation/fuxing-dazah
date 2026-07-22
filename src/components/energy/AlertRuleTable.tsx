'use client'

import { Table, Tag, Space, Button, Popconfirm } from 'antd'
import { EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { AlertRule, AlertLevel, EnergyType } from '@/types/energy'
import { energyTypeLabels } from './constants'
import { usePermission } from '@/hooks/usePermission'

interface AlertRuleTableProps {
  data: AlertRule[]
  loading?: boolean
  total?: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  onEdit: (record: AlertRule) => void
  onDelete: (id: string) => void
}

const alertLevelLabels: Record<AlertLevel, { text: string; color: string }> = {
  info: { text: '提示', color: 'blue' },
  warning: { text: '警告', color: 'orange' },
  critical: { text: '严重', color: 'red' },
  emergency: { text: '紧急', color: 'magenta' },
}

export function AlertRuleTable({
  data,
  loading = false,
  total = 0,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  onEdit,
  onDelete,
}: AlertRuleTableProps) {
  const { hasPermission } = usePermission()

  const handleDelete = async (id: string) => {
    await onDelete(id)
  }

  const columns: TableColumnsType<AlertRule> = [
    {
      title: '规则名称',
      dataIndex: 'rule_name',
      key: 'rule_name',
      width: 180,
    },
    {
      title: '车间',
      dataIndex: 'workshop',
      key: 'workshop',
      width: 120,
      render: (workshop: string | null) => workshop || '—',
    },
    {
      title: '能源类型',
      dataIndex: 'energy_type',
      key: 'energy_type',
      width: 100,
      render: (type: EnergyType) => {
        const { text, color } = energyTypeLabels[type]
        return <Tag color={color}>{text}</Tag>
      },
    },
    {
      title: '类型',
      dataIndex: 'is_system',
      key: 'is_system',
      width: 80,
      render: (isSystem: boolean) => (
        <Tag color={isSystem ? 'purple' : 'geekblue'}>
          {isSystem ? '系统' : '手动'}
        </Tag>
      ),
    },
    {
      title: '预警等级',
      dataIndex: 'alert_level',
      key: 'alert_level',
      width: 100,
      render: (level: AlertLevel) => {
        const { text, color } = alertLevelLabels[level]
        return <Tag color={color}>{text}</Tag>
      },
    },
    {
      title: '阈值',
      key: 'threshold',
      width: 150,
      render: (_, record) => (
        <span>
          {record.threshold_type === 'greater_than' ? '>' : record.threshold_type === 'less_than' ? '<' : '='}{' '}
          {record.threshold_value} {record.unit}
        </span>
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
          {hasPermission('energy:alert:update') && (
            <Button
              type="link"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            >
              编辑
            </Button>
          )}
          {hasPermission('energy:alert:delete') && (
            <Popconfirm
              title="确定删除此规则？"
              onConfirm={() => handleDelete(record.id)}
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
