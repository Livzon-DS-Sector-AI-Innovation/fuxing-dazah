'use client'

import { Alert, Table, Tag, Empty, Space } from 'antd'
import { WarningOutlined, ImportOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { StockWarning } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { usePermission } from '@/hooks/usePermission'
import { linkPurple } from '@/components/equipment/shared/shared-styles'

export function StockWarningTable() {
  const { stockWarnings, stockWarningsLoading, openStockInboundDrawer } = useEquipmentStore()
  const { hasPermission } = usePermission()
  const canUpdate = hasPermission('equipment:spare_part:update')

  const columns: ColumnsType<StockWarning> = [
    {
      title: '编码', dataIndex: 'code', key: 'code', width: 120,
      render: (v: string) => (
        <span style={{ fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, color: '#5d5b54' }}>{v}</span>
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
    {
      title: '当前库存', dataIndex: 'current_qty', key: 'current_qty', width: 100, align: 'right',
      render: (qty: number, record) => (
        <Space size={4}>
          <span style={{ color: '#e03131', fontWeight: 600 }}>{qty}</span>
          {record.unit ? <span style={{ color: '#a4a097', fontSize: 12 }}>{record.unit}</span> : null}
        </Space>
      ),
    },
    { title: '安全库存', dataIndex: 'min_qty', key: 'min_qty', width: 90, align: 'right' },
    {
      title: '缺口', dataIndex: 'shortage', key: 'shortage', width: 80, align: 'right',
      render: (shortage: number | undefined, record) => (
        <span style={{ color: '#e03131', fontWeight: 600 }}>
          -{shortage ?? Math.max(0, record.min_qty - record.current_qty)}
        </span>
      ),
    },
    {
      title: '建议补货量', dataIndex: 'suggested_qty', key: 'suggested_qty', width: 100, align: 'right',
      render: (v: number | undefined, record) => {
        if (v == null) return '-'
        return (
          <Space size={4}>
            <span style={{ fontWeight: 600 }}>{v}</span>
            {record.min_order_qty && record.min_order_qty > 1 && (
              <Tag style={{ fontSize: 11, lineHeight: '16px', marginInlineEnd: 0 }}>
                批量 ×{record.min_order_qty}
              </Tag>
            )}
          </Space>
        )
      },
    },
    {
      title: '库位', dataIndex: 'warehouse_location', key: 'warehouse_location', width: 80,
      render: (v: string | null | undefined) => v || '-',
    },
    ...(canUpdate ? [{
      title: '操作', key: 'action', width: 80,
      render: (_: unknown, record: StockWarning) => (
        <span role="button" onClick={() => openStockInboundDrawer(record.spare_part_id)} style={linkPurple}>
          <ImportOutlined /> 入库
        </span>
      ),
    }] : []),
  ]

  if (stockWarnings.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="没有低于安全库存的备件"
        style={{ padding: '48px 0' }}
      />
    )
  }

  return (
    <div>
      <Alert
        title={`${stockWarnings.length} 个备件库存低于安全线，请及时补货`}
        type="warning"
        showIcon
        icon={<WarningOutlined />}
        style={{ marginBottom: 16 }}
      />
      <Table
        columns={columns} dataSource={stockWarnings} rowKey="spare_part_id" size="small" loading={stockWarningsLoading}
        scroll={{ x: 'max-content' }}
        pagination={false}
      />
    </div>
  )
}
