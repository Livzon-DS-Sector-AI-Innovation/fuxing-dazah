'use client'

import { Alert, Table } from 'antd'
import { WarningOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { StockWarning } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'

interface StockWarningTableProps {
  onRefresh?: () => void
}

export function StockWarningTable({ onRefresh }: StockWarningTableProps) {
  const { stockWarnings, stockWarningsLoading } = useEquipmentStore()

  const columns: ColumnsType<StockWarning> = [
    {
      title: '编码', dataIndex: 'code', key: 'code', width: 120,
    },
    {
      title: '名称', dataIndex: 'name', key: 'name', width: 150,
    },
    {
      title: '当前库存', dataIndex: 'current_qty', key: 'current_qty', width: 100, align: 'right',
      render: (qty: number) => (
        <span style={{ color: '#e03131', fontWeight: 600 }}>{qty}</span>
      ),
    },
    {
      title: '最低库存', dataIndex: 'min_qty', key: 'min_qty', width: 100, align: 'right',
    },
    {
      title: '差额', key: 'difference', width: 100, align: 'right',
      render: (_: unknown, record: StockWarning) => {
        const diff = record.current_qty - record.min_qty
        return <span style={{ color: '#e03131', fontWeight: 600 }}>{diff}</span>
      },
    },
  ]

  return (
    <div>
      {stockWarnings.length > 0 && (
        <Alert
          message={`${stockWarnings.length} 个备件库存低于最低库存，请及时补充`}
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}
      <Table
        columns={columns} dataSource={stockWarnings} rowKey="spare_part_id" size="small" loading={stockWarningsLoading}
        scroll={{ x: 'max-content' }}
        pagination={false}
      />
    </div>
  )
}
