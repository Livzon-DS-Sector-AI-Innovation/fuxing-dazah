'use client'

import { useCallback } from 'react'
import { App, Table, Tag, Button, Space, Select } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { CalibrationPlan, CalibrationPlanStatus, CalibrationType } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteCalibrationPlan } from '@/actions/equipment'

const statusConfig: Record<CalibrationPlanStatus, { color: string; label: string; bgColor: string }> = {
  '启用': { color: '#1aae39', label: '启用', bgColor: '#e6f7e6' },
  '停用': { color: '#787671', label: '停用', bgColor: '#f0eeec' },
}

interface CalibrationPlanTableProps {
  onRefresh?: () => void
  onRecordRefresh?: () => void
}

export function CalibrationPlanTable({ onRefresh, onRecordRefresh }: CalibrationPlanTableProps) {
  const { message, modal } = App.useApp()
  const {
    calibrationPlans, calibrationPlanTotal, calibrationPlanPage, calibrationPlanPageSize,
    calibrationPlanLoading, calibrationPlanStatusFilter,
    setCalibrationPlanPage, setCalibrationPlanPageSize, setCalibrationPlanStatusFilter,
    openCalibrationPlanDrawer, openCalibrationRecordDrawer,
  } = useEquipmentStore()

  const handleDelete = useCallback((record: CalibrationPlan) => {
    modal.confirm({
      title: '确认删除',
      content: '确定要删除此校准计划吗？',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteCalibrationPlan(record.id)
          message.success('删除成功')
          onRefresh?.()
        } catch (error: any) {
          message.error(error?.message || '删除失败')
        }
      },
    })
  }, [modal, message, onRefresh])

  const isOverdue = (dateStr: string | null): boolean => {
    if (!dateStr) return false
    return new Date(dateStr) < new Date()
  }

  const columns: ColumnsType<CalibrationPlan> = [
    {
      title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 150,
      render: (name: string | undefined, record) => name || record.equipment_id,
    },
    {
      title: '校准类型', dataIndex: 'calibration_type', key: 'calibration_type', width: 110,
      render: (type: CalibrationType) => (
        <Tag style={{
          color: type === '内部校准' ? '#5645d4' : '#dd5b00',
          background: type === '内部校准' ? '#ede9f7' : '#fff7e6',
          border: 'none', borderRadius: 4, fontWeight: 500,
        }}>{type}</Tag>
      ),
    },
    {
      title: '校准周期', dataIndex: 'cycle_months', key: 'cycle_months', width: 100,
      render: (months: number) => `${months}个月`,
    },
    {
      title: '上次校准', dataIndex: 'last_calibration_date', key: 'last_calibration_date', width: 110,
      render: (date: string | null) => date || '-',
    },
    {
      title: '下次校准', dataIndex: 'next_calibration_date', key: 'next_calibration_date', width: 120,
      render: (date: string | null) => {
        if (!date) return '-'
        const overdue = isOverdue(date)
        return (
          <span style={{ color: overdue ? '#e03131' : '#1a1a1a', fontWeight: overdue ? 600 : 400 }}>
            {date}
            {overdue && <Tag color="error" style={{ marginLeft: 4, fontSize: 11 }}>逾期</Tag>}
          </span>
        )
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (status: CalibrationPlanStatus) => {
        const config = statusConfig[status]
        return <Tag style={{ color: config.color, background: config.bgColor, border: 'none', borderRadius: 4 }}>{config.label}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 180, fixed: 'end',
      render: (_: unknown, record: CalibrationPlan) => (
        <Space>
          <Button type="link" icon={<FileTextOutlined />}
            onClick={() => openCalibrationRecordDrawer({ calibration_plan_id: record.id, calibration_type: record.calibration_type } as any)}
            style={{ padding: 0 }}>记录</Button>
          <Button type="link" icon={<EditOutlined />} onClick={() => openCalibrationPlanDrawer(record)} style={{ padding: 0 }}>编辑</Button>
          <Button type="link" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record)} style={{ padding: 0 }}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Select
          placeholder="计划状态" allowClear style={{ width: 120 }}
          value={calibrationPlanStatusFilter || undefined}
          onChange={(v) => setCalibrationPlanStatusFilter(v || '')}
          options={[{ label: '启用', value: '启用' }, { label: '停用', value: '停用' }]}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openCalibrationPlanDrawer()}>
          新增校准计划
        </Button>
      </div>
      <Table
        columns={columns} dataSource={calibrationPlans} rowKey="id" size="small" loading={calibrationPlanLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: calibrationPlanPage, pageSize: calibrationPlanPageSize, total: calibrationPlanTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: (t) => `共 ${t} 条`,
          onChange: (p, s) => { setCalibrationPlanPage(p); setCalibrationPlanPageSize(s) },
        }}
      />
    </div>
  )
}
