'use client'

import { Table, Space, Select } from 'antd'
import { EditOutlined, EyeOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { WorkOrder, WorkOrderStatus, WorkOrderPriority, WorkOrderType } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { statusPill, pillSuccess, pillError, pillWarning, pillPurple, pillNeutral, pillInfo, actionLink, linkPrimary, linkPurple } from '@/components/equipment/shared/shared-styles'

const statusColorMap: Record<WorkOrderStatus, React.CSSProperties> = {
  '待处理': pillError,
  '执行中': pillWarning,
  '待验收': statusPill('#d4b106', '#fffbe6'),
  '已完成': pillSuccess,
  '已关闭': pillNeutral,
}

const priorityColorMap: Record<WorkOrderPriority, React.CSSProperties> = {
  '紧急': pillError,
  '高':   pillWarning,
  '中':   pillPurple,
  '低':   pillNeutral,
}

const statusOptions = Object.keys(statusColorMap).map(v => ({ label: v, value: v }))
const priorityOptions: { label: string; value: WorkOrderPriority }[] = [
  { label: '紧急', value: '紧急' }, { label: '高', value: '高' },
  { label: '中', value: '中' }, { label: '低', value: '低' },
]
const typeOptions: { label: string; value: WorkOrderType }[] = [
  { label: '故障维修', value: '故障维修' }, { label: '计划维护', value: '计划维护' },
  { label: '校准', value: '校准' },
  { label: '异常处理', value: '异常处理' }, { label: '日常维护', value: '日常维护' },
]

interface Props { onRefresh?: () => void }

export function WorkOrderTable({ onRefresh }: Props) {
  const {
    workOrders, workOrderTotal, workOrderPage, workOrderPageSize, workOrderLoading,
    workOrderStatusFilter, workOrderPriorityFilter, workOrderTypeFilter,
    setWorkOrderPage, setWorkOrderPageSize,
    setWorkOrderStatusFilter, setWorkOrderPriorityFilter, setWorkOrderTypeFilter,
    openWorkOrderDrawer, openWorkOrderDetail,
  } = useEquipmentStore()

  const columns: ColumnsType<WorkOrder> = [
    { title: '工单号', dataIndex: 'work_order_no', key: 'work_order_no', width: 160, fixed: 'start' },
    {
      title: '设备名称', dataIndex: 'equipment_name', key: 'equipment_name', width: 150, ellipsis: true,
      render: (t: string | null) => t || '-',
    },
    {
      title: '工单类型', dataIndex: 'order_type', key: 'order_type', width: 100,
      render: (t: WorkOrderType) => {
        const typeStyle =
          t === '故障维修' || t === '异常处理' ? pillWarning :
          t === '日常维护' ? pillInfo :
          pillPurple
        return <span style={typeStyle}>{t}</span>
      },
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 80,
      render: (p: WorkOrderPriority) => <span style={priorityColorMap[p]}>{p}</span>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: WorkOrderStatus) => <span style={statusColorMap[s]}>{s}</span>,
    },
    { title: '故障描述', dataIndex: 'fault_description', key: 'fault_description', width: 200, ellipsis: true, render: (t: string | null) => t || '-' },
    {
      title: '报修时间', dataIndex: 'reported_at', key: 'reported_at', width: 170,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '维修耗时', dataIndex: 'actual_duration', key: 'actual_duration', width: 100,
      render: (d: number | null) => {
        if (d === null || d === undefined) return '-'
        if (d < 60) return `${d}分钟`
        const h = Math.floor(d / 60); const m = d % 60
        return m > 0 ? `${h}小时${m}分` : `${h}小时`
      },
    },
    {
      title: '操作', key: 'action', width: 150, fixed: 'end',
      render: (_: unknown, r: WorkOrder) => (
        <Space size={12}>
          <span role="button" onClick={() => openWorkOrderDetail(r)} style={linkPrimary}><EyeOutlined />详情</span>
          {r.status === '待处理' && (
            <span role="button" onClick={() => openWorkOrderDrawer(r)} style={linkPurple}><EditOutlined />编辑</span>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Select placeholder="工单状态" allowClear style={{ width: 120 }}
          value={workOrderStatusFilter || undefined} onChange={v => setWorkOrderStatusFilter(v || '')} options={statusOptions} />
        <Select placeholder="优先级" allowClear style={{ width: 100 }}
          value={workOrderPriorityFilter || undefined} onChange={v => setWorkOrderPriorityFilter(v || '')} options={priorityOptions} />
        <Select placeholder="工单类型" allowClear style={{ width: 120 }}
          value={workOrderTypeFilter || undefined} onChange={v => setWorkOrderTypeFilter(v || '')} options={typeOptions} />
      </div>
      <Table columns={columns} dataSource={workOrders} rowKey="id" size="small" loading={workOrderLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: workOrderPage, pageSize: workOrderPageSize, total: workOrderTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== workOrderPageSize) { setWorkOrderPageSize(s) } else { setWorkOrderPage(p) } },
        }} />
    </div>
  )
}
