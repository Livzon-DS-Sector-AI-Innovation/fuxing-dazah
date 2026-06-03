'use client'

import { Table, Tag, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { CalibrationRecord, CalibrationType, CalibrationResult } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

interface CalibrationRecordTableProps {
  onRefresh?: () => void
}

export function CalibrationRecordTable({ onRefresh }: CalibrationRecordTableProps) {
  const {
    calibrationRecords, calibrationRecordTotal, calibrationRecordPage, calibrationRecordPageSize,
    calibrationRecordLoading, setCalibrationRecordPage, setCalibrationRecordPageSize,
    openCalibrationRecordDrawer,
  } = useEquipmentStore()

  const columns: ColumnsType<CalibrationRecord> = [
    {
      title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 150,
      render: (name: string | undefined, record) => name || record.equipment_id,
    },
    { title: '校准日期', dataIndex: 'calibration_date', key: 'calibration_date', width: 110 },
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
      title: '校准结果', dataIndex: 'result', key: 'result', width: 90,
      render: (result: CalibrationResult) => (
        <Tag style={{
          color: result === '合格' ? '#1aae39' : '#e03131',
          background: result === '合格' ? '#e6f7e6' : '#fff1f0',
          border: 'none', borderRadius: 4, fontWeight: 500,
        }}>{result}</Tag>
      ),
    },
    { title: '证书编号', dataIndex: 'certificate_no', key: 'certificate_no', width: 140, render: (t: string | null) => t || '-' },
    { title: '校准单位/人员', dataIndex: 'calibrated_by', key: 'calibrated_by', width: 140, render: (t: string | null) => t || '-' },
    { title: '下次校准日期', dataIndex: 'next_due_date', key: 'next_due_date', width: 120 },
    { title: '备注', dataIndex: 'remark', key: 'remark', ellipsis: true, render: (t: string | null) => t || '-' },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openCalibrationRecordDrawer()}>
          新增校准记录
        </Button>
      </div>
      <Table
        columns={columns} dataSource={calibrationRecords} rowKey="id" size="small" loading={calibrationRecordLoading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: calibrationRecordPage, pageSize: calibrationRecordPageSize, total: calibrationRecordTotal,
          showSizeChanger: true, showQuickJumper: true, showTotal: (t) => `共 ${t} 条`,
          onChange: (p, s) => { setCalibrationRecordPage(p); setCalibrationRecordPageSize(s) },
        }}
      />
    </div>
  )
}
