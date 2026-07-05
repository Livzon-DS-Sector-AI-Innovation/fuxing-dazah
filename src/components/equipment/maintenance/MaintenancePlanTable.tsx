'use client'

import { useCallback } from 'react'
import { App, Table, Space, Select, Input } from 'antd'
import { EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { MaintenancePlan, MaintenancePlanStatus } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteMaintenancePlan } from '@/actions/equipment'
import { pillSuccess, pillNeutral, pillPurple, pillWarning, pillError, linkPrimary, linkDanger } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

const statusMap: Record<MaintenancePlanStatus, React.CSSProperties> = {
  '启用': pillSuccess,
  '停用': pillNeutral,
  '已完成': pillPurple,
}

interface Props { onRefresh?: () => void; equipments: { id: string; name: string; equipment_no: string }[] }

export function MaintenancePlanTable({ onRefresh, equipments }: Props) {
  const { message, modal } = App.useApp()
  const {
    maintenancePlans, maintenancePlanTotal, maintenancePlanPage, maintenancePlanPageSize,
    maintenancePlanLoading, maintenancePlanStatusFilter, maintenancePlanKeyword,
    setMaintenancePlanPage, setMaintenancePlanPageSize, setMaintenancePlanStatusFilter,
    setMaintenancePlanKeyword, openMaintenancePlanDrawer,
  } = useEquipmentStore()
  const { hasPermission } = usePermission()

  const handleDelete = useCallback((r: MaintenancePlan) => {
    modal.confirm({
      title: '确认删除', content: '确定要删除此维护计划吗？',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteMaintenancePlan(r.id)
        if (!result.success) { message.error(result.error); return }
        message.success('删除成功'); onRefresh?.()
      },
    })
  }, [modal, message, onRefresh])

  const isOverdue = (d: string | null) => d ? new Date(d) < new Date() : false

  const columns: ColumnsType<MaintenancePlan> = [
    { title: '计划名称', dataIndex: 'plan_name', key: 'plan_name', width: 160 },
    {
      title: '关联', dataIndex: 'equipment_name', key: 'target', width: 150,
      render: (_: unknown, r: MaintenancePlan) => {
        if (r.equipment_name) return r.equipment_name
        if (r.category_name) return `[分类] ${r.category_name}`
        return '-'
      },
    },
    {
      title: '关联方式', key: 'plan_mode', width: 90,
      render: (_: unknown, r: MaintenancePlan) => r.category_id ? '按分类' : '按设备',
    },
    {
      title: '执行人', dataIndex: 'executor_name', key: 'executor_name', width: 100,
      render: (t: string | null) => t || '-',
    },
    {
      title: '维护类型', dataIndex: 'plan_type', key: 'plan_type', width: 110,
      render: (t: string) => <span style={t === '预防性维护' ? pillPurple : pillWarning}>{t}</span>,
    },
    { title: '维护频率', key: 'frequency', width: 110, render: (_: unknown, r: MaintenancePlan) => `${r.frequency}${r.frequency_unit}` },
    { title: '上次维护', dataIndex: 'last_maintenance_date', key: 'last_maintenance_date', width: 110, render: (d: string | null) => d || '-' },
    {
      title: '下次维护', dataIndex: 'next_maintenance_date', key: 'next_maintenance_date', width: 120,
      render: (d: string | null) => {
        if (!d) return '-'
        const overdue = isOverdue(d)
        return <span style={{ color: overdue ? '#e03131' : '#1a1a1a', fontWeight: overdue ? 600 : 400 }}>{d}{overdue && <span style={{ marginLeft: 6 }}><span style={pillError}>逾期</span></span>}</span>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: MaintenancePlanStatus) => <span style={statusMap[s]}>{s}</span>,
    },
    {
      title: '操作', key: 'action', width: 150, fixed: 'end',
      render: (_: unknown, r: MaintenancePlan) => (
        <Space size={12}>
          {hasPermission('equipment:maintenance:update') && (
            <span role="button" onClick={() => openMaintenancePlanDrawer(r)} style={linkPrimary}><EditOutlined />编辑</span>
          )}
          {hasPermission('equipment:maintenance:delete') && (
            <span role="button" onClick={() => handleDelete(r)} style={linkDanger}><DeleteOutlined />删除</span>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-start', alignItems: 'center' }}>
        <Space>
          <Select placeholder="计划状态" allowClear style={{ width: 120 }}
            value={maintenancePlanStatusFilter || undefined} onChange={v => setMaintenancePlanStatusFilter(v || '')}
            options={[{ label: '启用', value: '启用' }, { label: '停用', value: '停用' }, { label: '已完成', value: '已完成' }]} />
          <Input.Search placeholder="搜索计划名称" allowClear style={{ width: 200 }}
            value={maintenancePlanKeyword || undefined} onSearch={v => setMaintenancePlanKeyword(v)} />
        </Space>
      </div>
      <Table columns={columns} dataSource={maintenancePlans} rowKey="id" size="small" loading={maintenancePlanLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: maintenancePlanPage, pageSize: maintenancePlanPageSize, total: maintenancePlanTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== maintenancePlanPageSize) { setMaintenancePlanPageSize(s) } else { setMaintenancePlanPage(p) } },
        }} />
    </div>
  )
}
