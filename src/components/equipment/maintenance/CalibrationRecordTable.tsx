'use client'

import { Table, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { CalibrationRecord, CalibrationType, CalibrationResult } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { pillSuccess, pillError, pillPurple, pillWarning, statusPill } from '@/components/equipment/shared/shared-styles'
import { usePermission } from '@/hooks/usePermission'

interface Props { onRefresh?: () => void }

export function CalibrationRecordTable({ onRefresh }: Props) {
  const {
    calibrationRecords, calibrationRecordTotal, calibrationRecordPage, calibrationRecordPageSize,
    calibrationRecordLoading, setCalibrationRecordPage, setCalibrationRecordPageSize,
    openCalibrationRecordDrawer,
  } = useEquipmentStore()

  const { hasPermission } = usePermission()

  const columns: ColumnsType<CalibrationRecord> = [
    { title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 150, render: (n: string | undefined, r) => n || r.equipment_id },
    { title: '校准日期', dataIndex: 'calibration_date', key: 'calibration_date', width: 110 },
    {
      title: '校准类型', dataIndex: 'calibration_type', key: 'calibration_type', width: 110,
      render: (t: CalibrationType) => <span style={t === '内部校准' ? pillPurple : pillWarning}>{t}</span>,
    },
    {
      title: '校准结果', dataIndex: 'result', key: 'result', width: 90,
      render: (r: CalibrationResult) => <span style={r === '合格' ? pillSuccess : pillError}>{r}</span>,
    },
    { title: '证书编号', dataIndex: 'certificate_no', key: 'certificate_no', width: 140, render: (t: string | null) => t || '-' },
    { title: '校准单位/人员', dataIndex: 'calibrated_by', key: 'calibrated_by', width: 140, render: (t: string | null) => t || '-' },
    { title: '下次校准日期', dataIndex: 'next_due_date', key: 'next_due_date', width: 120 },
    { title: '备注', dataIndex: 'remark', key: 'remark', ellipsis: true, render: (t: string | null) => t || '-' },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
        {hasPermission('equipment:maintenance:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCalibrationRecordDrawer()}>新增校准记录</Button>
        )}
      </div>
      <Table columns={columns} dataSource={calibrationRecords} rowKey="id" size="small" loading={calibrationRecordLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: calibrationRecordPage, pageSize: calibrationRecordPageSize, total: calibrationRecordTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: t => `共 ${t} 条`,
          onChange: (p, s) => { if (s !== calibrationRecordPageSize) { setCalibrationRecordPageSize(s) } else { setCalibrationRecordPage(p) } },
        }} />
    </div>
  )
}
