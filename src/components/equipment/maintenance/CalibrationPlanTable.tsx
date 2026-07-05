'use client'

import { useCallback } from 'react'
import { App, Table, Button, Space, Select } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { CalibrationPlan, CalibrationPlanStatus, CalibrationType } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteCalibrationPlan } from '@/actions/equipment'
import { pillSuccess, pillNeutral, pillPurple, pillWarning, pillError, statusPill, actionLink, linkPrimary, linkDanger, linkPurple } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

const statusMap: Record<CalibrationPlanStatus, React.CSSProperties> = {
  '启用': pillSuccess,
  '停用': pillNeutral,
}

interface Props { onRefresh?: () => void; onRecordRefresh?: () => void }

export function CalibrationPlanTable({ onRefresh, onRecordRefresh }: Props) {
  const { message, modal } = App.useApp()
  const {
    calibrationPlans, calibrationPlanTotal, calibrationPlanPage, calibrationPlanPageSize,
    calibrationPlanLoading, calibrationPlanStatusFilter,
    setCalibrationPlanPage, setCalibrationPlanPageSize, setCalibrationPlanStatusFilter,
    openCalibrationPlanDrawer, openCalibrationRecordDrawer,
  } = useEquipmentStore()

  const { hasPermission } = usePermission()

  const handleDelete = useCallback((r: CalibrationPlan) => {
    modal.confirm({
      title: '确认删除', content: '确定要删除此校准计划吗？',
      okText: '确认', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteCalibrationPlan(r.id)
        if (!result.success) { message.error(result.error); return }
        message.success('删除成功'); onRefresh?.()
      },
    })
  }, [modal, message, onRefresh])

  const isOverdue = (d: string | null) => d ? new Date(d) < new Date() : false

  const columns: ColumnsType<CalibrationPlan> = [
    { title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 150, render: (n: string | undefined, r) => n || r.equipment_id },
    {
      title: '校准类型', dataIndex: 'calibration_type', key: 'calibration_type', width: 110,
      render: (t: CalibrationType) => <span style={t === '内部校准' ? pillPurple : pillWarning}>{t}</span>,
    },
    { title: '校准周期', dataIndex: 'cycle_months', key: 'cycle_months', width: 100, render: (m: number) => `${m}个月` },
    { title: '上次校准', dataIndex: 'last_calibration_date', key: 'last_calibration_date', width: 110, render: (d: string | null) => d || '-' },
    {
      title: '下次校准', dataIndex: 'next_calibration_date', key: 'next_calibration_date', width: 120,
      render: (d: string | null) => {
        if (!d) return '-'
        const overdue = isOverdue(d)
        return <span style={{ color: overdue ? '#e03131' : '#1a1a1a', fontWeight: overdue ? 600 : 400 }}>{d}{overdue && <span style={{ marginLeft: 6 }}><span style={pillError}>逾期</span></span>}</span>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: CalibrationPlanStatus) => <span style={statusMap[s]}>{s}</span>,
    },
    {
      title: '操作', key: 'action', width: 180, fixed: 'end',
      render: (_: unknown, r: CalibrationPlan) => (
        <Space size={12}>
          {hasPermission('equipment:maintenance:create') && (
            <span role="button" onClick={() => openCalibrationRecordDrawer({ calibration_plan_id: r.id, calibration_type: r.calibration_type } as any)} style={linkPurple}><FileTextOutlined />记录</span>
          )}
          {hasPermission('equipment:maintenance:update') && (
            <span role="button" onClick={() => openCalibrationPlanDrawer(r)} style={linkPrimary}><EditOutlined />编辑</span>
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
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Select placeholder="计划状态" allowClear style={{ width: 120 }}
          value={calibrationPlanStatusFilter || undefined} onChange={v => setCalibrationPlanStatusFilter(v || '')}
          options={[{ label: '启用', value: '启用' }, { label: '停用', value: '停用' }]} />
        {hasPermission('equipment:maintenance:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCalibrationPlanDrawer()}>新增校准计划</Button>
        )}
      </div>
      <Table columns={columns} dataSource={calibrationPlans} rowKey="id" size="small" loading={calibrationPlanLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: calibrationPlanPage, pageSize: calibrationPlanPageSize, total: calibrationPlanTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== calibrationPlanPageSize) { setCalibrationPlanPageSize(s) } else { setCalibrationPlanPage(p) } },
        }} />
    </div>
  )
}
