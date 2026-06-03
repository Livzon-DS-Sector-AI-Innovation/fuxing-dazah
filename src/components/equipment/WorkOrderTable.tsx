'use client'

import { useCallback } from 'react'
import { App, Table, Tag, Space, Button, Select } from 'antd'
import { EditOutlined, EyeOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { WorkOrder, WorkOrderStatus, WorkOrderPriority, WorkOrderType } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

const statusConfig: Record<WorkOrderStatus, { color: string; label: string; bgColor: string }> = {
  '待处理': { color: '#e03131', label: '待处理', bgColor: '#fff1f0' },
  '已指派': { color: '#5645d4', label: '已指派', bgColor: '#ede9f7' },
  '维修中': { color: '#dd5b00', label: '维修中', bgColor: '#fff7e6' },
  '待验收': { color: '#d4b106', label: '待验收', bgColor: '#fffbe6' },
  '已完成': { color: '#1aae39', label: '已完成', bgColor: '#e6f7e6' },
  '已关闭': { color: '#787671', label: '已关闭', bgColor: '#f0eeec' },
}

const priorityConfig: Record<WorkOrderPriority, { color: string; bgColor: string }> = {
  '紧急': { color: '#e03131', bgColor: '#fff1f0' },
  '高': { color: '#dd5b00', bgColor: '#fff7e6' },
  '中': { color: '#5645d4', bgColor: '#ede9f7' },
  '低': { color: '#787671', bgColor: '#f0eeec' },
}

const statusOptions = Object.entries(statusConfig).map(([value, { label }]) => ({ label, value }))
const priorityOptions: { label: string; value: WorkOrderPriority }[] = [
  { label: '紧急', value: '紧急' },
  { label: '高', value: '高' },
  { label: '中', value: '中' },
  { label: '低', value: '低' },
]
const typeOptions: { label: string; value: WorkOrderType }[] = [
  { label: '故障维修', value: '故障维修' },
  { label: '校准', value: '校准' },
]

interface WorkOrderTableProps {
  onRefresh?: () => void
}

export function WorkOrderTable({ onRefresh }: WorkOrderTableProps) {
  const {
    workOrders, workOrderTotal, workOrderPage, workOrderPageSize, workOrderLoading,
    workOrderStatusFilter, workOrderPriorityFilter, workOrderTypeFilter,
    setWorkOrderPage, setWorkOrderPageSize,
    setWorkOrderStatusFilter, setWorkOrderPriorityFilter, setWorkOrderTypeFilter,
    openWorkOrderDrawer, openWorkOrderDetail,
  } = useEquipmentStore()

  const columns: ColumnsType<WorkOrder> = [
    {
      title: '工单号',
      dataIndex: 'work_order_no',
      key: 'work_order_no',
      width: 160,
      fixed: 'start',
    },
    {
      title: '工单类型',
      dataIndex: 'order_type',
      key: 'order_type',
      width: 100,
      render: (type: WorkOrderType) => (
        <Tag style={{
          color: type === '故障维修' ? '#dd5b00' : '#5645d4',
          background: type === '故障维修' ? '#fff7e6' : '#ede9f7',
          border: 'none', borderRadius: 4, fontWeight: 500,
        }}>
          {type}
        </Tag>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (priority: WorkOrderPriority) => {
        const config = priorityConfig[priority]
        return (
          <Tag style={{ color: config.color, background: config.bgColor, border: 'none', borderRadius: 4, fontWeight: 500 }}>
            {priority}
          </Tag>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: WorkOrderStatus) => {
        const config = statusConfig[status]
        return (
          <Tag style={{ color: config.color, background: config.bgColor, border: 'none', borderRadius: 4, fontWeight: 500 }}>
            {config.label}
          </Tag>
        )
      },
    },
    {
      title: '故障描述',
      dataIndex: 'fault_description',
      key: 'fault_description',
      width: 200,
      ellipsis: true,
      render: (text: string | null) => text || '-',
    },
    {
      title: '报修时间',
      dataIndex: 'reported_at',
      key: 'reported_at',
      width: 170,
      render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '维修耗时',
      dataIndex: 'actual_duration',
      key: 'actual_duration',
      width: 100,
      render: (duration: number | null) => {
        if (duration === null || duration === undefined) return '-'
        if (duration < 60) return `${duration}分钟`
        const hours = Math.floor(duration / 60)
        const mins = duration % 60
        return mins > 0 ? `${hours}小时${mins}分` : `${hours}小时`
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'end',
      render: (_: unknown, record: WorkOrder) => (
        <Space>
          <Button type="link" icon={<EyeOutlined />} onClick={() => openWorkOrderDetail(record)} style={{ padding: 0 }}>
            详情
          </Button>
          {record.status === '待处理' && (
            <Button type="link" icon={<EditOutlined />} onClick={() => openWorkOrderDrawer(record)} style={{ padding: 0 }}>
              编辑
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Select placeholder="工单状态" allowClear style={{ width: 120 }}
          value={workOrderStatusFilter || undefined} onChange={(v) => setWorkOrderStatusFilter(v || '')} options={statusOptions} />
        <Select placeholder="优先级" allowClear style={{ width: 100 }}
          value={workOrderPriorityFilter || undefined} onChange={(v) => setWorkOrderPriorityFilter(v || '')} options={priorityOptions} />
        <Select placeholder="工单类型" allowClear style={{ width: 120 }}
          value={workOrderTypeFilter || undefined} onChange={(v) => setWorkOrderTypeFilter(v || '')} options={typeOptions} />
      </div>
      <Table
        columns={columns}
        dataSource={workOrders}
        rowKey="id"
        size="small"
        loading={workOrderLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: workOrderPage,
          pageSize: workOrderPageSize,
          total: workOrderTotal,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (p, s) => { setWorkOrderPage(p); setWorkOrderPageSize(s) },
        }}
      />
    </div>
  )
}
