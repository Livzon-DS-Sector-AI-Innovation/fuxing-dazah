'use client'

import {
  App,
  Alert,
  Empty,
  Modal,
  Spin,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { WarningOutlined } from '@ant-design/icons'
import { releasePlanOrder } from '@/actions/production'
import type { PlanItem } from '@/types/production'

const { Text } = Typography

interface Props {
  orderId: string
  open: boolean
  items: PlanItem[]
  isLoading?: boolean
  onClose: () => void
  onRefresh: () => void
}

export function ReleaseConfirmModal({ orderId, open, items, isLoading = false, onClose, onRefresh }: Props) {
  const { message } = App.useApp()

  const itemsWithoutRoute = items.filter(i => !i.route_id)
  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleDateString('zh-CN') : '—')

  const columns: ColumnsType<PlanItem> = [
    { title: '项号', dataIndex: 'item_no', key: 'item_no', width: 60 },
    { title: '产出物', dataIndex: 'intermediate_type_name', key: 'intermediate_type_name', width: 140 },
    {
      title: '计划数量',
      key: 'qty',
      width: 100,
      render: (_, r) => `${r.planned_quantity}${r.unit ? ` ${r.unit}` : ''}`,
    },
    { title: '设备', dataIndex: 'equipment_id', key: 'equipment_id', width: 100, render: v => v || '—' },
    {
      title: '计划时间',
      key: 'dates',
      width: 180,
      render: (_, r) => `${formatDate(r.planned_start)} ~ ${formatDate(r.planned_end)}`,
    },
    {
      title: '路线',
      dataIndex: 'route_id',
      key: 'route_id',
      width: 80,
      render: (v: string | null) => (v ? <Text type="success">已设置</Text> : <Text type="danger">未设置</Text>),
    },
  ]

  const handleRelease = async () => {
    const r = await releasePlanOrder(orderId)
    if (r.success) {
      message.success('已下达')
      onRefresh()
      onClose()
    } else {
      message.error(r.error)
    }
  }

  return (
    <Modal
      title="下达确认"
      open={open}
      onOk={handleRelease}
      onCancel={onClose}
      okText="确认下达"
      cancelText="取消"
      width={700}
      destroyOnHidden
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : (
        <>
          {itemsWithoutRoute.length > 0 && (
            <Alert
              type="warning"
              showIcon
              icon={<WarningOutlined />}
              title={`${itemsWithoutRoute.length} 个计划项未设置工艺路线，下达后需手动排程。`}
              style={{ marginBottom: 16 }}
            />
          )}

          {items.length === 0 ? (
            <Empty description="无计划项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table<PlanItem>
              dataSource={items}
              columns={columns}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: 660 }}
            />
          )}
        </>
      )}
    </Modal>
  )
}
