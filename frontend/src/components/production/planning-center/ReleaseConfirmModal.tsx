'use client'

import { useState } from 'react'
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
import dayjs from 'dayjs'
import { releasePlanOrder } from '@/actions/production'
import type { PlanItem } from '@/types/production'

const { Text } = Typography

interface Props {
  orderId: string
  orderNo?: string
  open: boolean
  items: PlanItem[]
  isLoading?: boolean
  onClose: () => void
  onRefresh: () => void
}

const fmtDateTime = (d: string | null) => (d ? dayjs(d).format('YYYY-MM-DD HH:mm') : '—')
const fmtQty = (v: number) => v.toLocaleString('zh-CN', { maximumFractionDigits: 3 })

function StatCell({ label, value, last }: { label: string; value: React.ReactNode; last?: boolean }) {
  return (
    <div style={{
      flex: 1, minWidth: 0, padding: '0 14px',
      borderRight: last ? undefined : '1px solid var(--color-hairline-soft)',
    }}>
      <div style={{ fontSize: 11, color: 'var(--color-steel)', marginBottom: 3 }}>{label}</div>
      <div style={{
        fontSize: 14, fontWeight: 600, color: 'var(--color-charcoal)',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{value}</div>
    </div>
  )
}

export function ReleaseConfirmModal({ orderId, orderNo, open, items, isLoading = false, onClose, onRefresh }: Props) {
  const { message } = App.useApp()
  const [releasing, setReleasing] = useState(false)

  const sortedItems = [...items].sort((a, b) => a.item_no - b.item_no)
  // 与后端 release_plan_order 的校验口径一致：缺路线、未排程都会直接拒绝下达
  const missingRoute = sortedItems.filter(i => !i.route_id)
  const unscheduled = sortedItems.filter(i => i.status !== 'scheduled')
  const missingQty = sortedItems.filter(i => i.planned_quantity == null)
  const missingBatchNo = sortedItems.filter(i => !i.batch_no)
  const blocked = missingRoute.length > 0 || unscheduled.length > 0

  const qtyByUnit = new Map<string, number>()
  sortedItems.forEach(i => {
    if (i.planned_quantity == null) return
    const unit = i.unit || ''
    qtyByUnit.set(unit, (qtyByUnit.get(unit) ?? 0) + i.planned_quantity)
  })
  const qtySummary = qtyByUnit.size
    ? [...qtyByUnit].map(([unit, qty]) => `${fmtQty(qty)}${unit ? ` ${unit}` : ''}`).join(' + ')
    : '未填写'

  const starts = sortedItems.map(i => i.planned_start).filter((d): d is string => !!d)
  const ends = sortedItems.map(i => i.planned_end).filter((d): d is string => !!d)
  const minStart = starts.length
    ? starts.reduce((a, b) => (dayjs(a).isBefore(dayjs(b)) ? a : b))
    : null
  const maxEnd = ends.length
    ? ends.reduce((a, b) => (dayjs(a).isAfter(dayjs(b)) ? a : b))
    : null
  const timeSummary = `${minStart ? dayjs(minStart).format('YYYY-MM-DD') : '—'} ~ ${maxEnd ? dayjs(maxEnd).format('YYYY-MM-DD') : '—'}`

  const columns: ColumnsType<PlanItem> = [
    { title: '项号', dataIndex: 'item_no', key: 'item_no', width: 56, align: 'center' },
    {
      title: '批次号',
      dataIndex: 'batch_no',
      key: 'batch_no',
      width: 150,
      render: (v: string | null, r) => v
        ? <Text strong>{v}</Text>
        : (
          <Text type="secondary" title="未填写批次号，下达时自动生成">
            {orderNo ? `${orderNo}-${r.item_no}` : '自动生成'}
          </Text>
        ),
    },
    {
      title: '产品',
      dataIndex: 'product_name',
      key: 'product_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '计划数量',
      key: 'qty',
      width: 100,
      render: (_, r) => r.planned_quantity != null
        ? `${fmtQty(r.planned_quantity)}${r.unit ? ` ${r.unit}` : ''}`
        : <Text type="secondary">未填写</Text>,
    },
    {
      title: '设备',
      key: 'equipment',
      width: 130,
      ellipsis: true,
      render: (_, r) => {
        if (!r.equipment_id) return <Text type="secondary">未指定</Text>
        const name = r.equipment_name || r.equipment_no || '已指定'
        return r.equipment_name && r.equipment_no ? `${name}（${r.equipment_no}）` : name
      },
    },
    {
      title: '计划时间',
      key: 'dates',
      width: 180,
      render: (_, r) => (
        <div style={{ fontSize: 12, lineHeight: '18px', whiteSpace: 'nowrap' }}>
          <div><span style={{ color: 'var(--color-steel)' }}>起 </span>{fmtDateTime(r.planned_start)}</div>
          <div><span style={{ color: 'var(--color-steel)' }}>止 </span>{fmtDateTime(r.planned_end)}</div>
        </div>
      ),
    },
    {
      title: '路线',
      dataIndex: 'route_id',
      key: 'route_id',
      width: 76,
      render: (v: string | null) => (v ? <Text type="success">已设置</Text> : <Text type="danger">未设置</Text>),
    },
  ]

  const handleRelease = async () => {
    setReleasing(true)
    try {
      const r = await releasePlanOrder(orderId)
      if (r.success) {
        message.success('已下达')
        onRefresh()
        onClose()
      } else {
        message.error(r.error)
      }
    } finally {
      setReleasing(false)
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
      okButtonProps={{ disabled: blocked }}
      confirmLoading={releasing}
      width={880}
      destroyOnHidden
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : items.length === 0 ? (
        <Empty description="无计划项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div style={{
            display: 'flex', alignItems: 'center',
            background: 'var(--color-surface-soft)', borderRadius: 8,
            padding: '10px 0', marginBottom: 12,
          }}>
            <StatCell label="计划项" value={`${sortedItems.length} 项`} />
            <StatCell label="计划数量" value={qtySummary} />
            <StatCell label="计划时间" value={timeSummary} last />
          </div>

          {blocked && (
            <Alert
              type="error"
              showIcon
              title="当前计划项不满足下达条件"
              description={(
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {missingRoute.length > 0 && (
                    <span>{missingRoute.length} 个计划项未设置工艺路线，无法生成批次</span>
                  )}
                  {unscheduled.length > 0 && (
                    <span>{unscheduled.length} 个计划项未完成排程，需先设置计划开始与结束时间</span>
                  )}
                </div>
              )}
              style={{ marginBottom: 12 }}
            />
          )}

          {(missingQty.length > 0 || missingBatchNo.length > 0) && (
            <Alert
              type="warning"
              showIcon
              icon={<WarningOutlined />}
              title="下达前请确认"
              description={(
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {missingQty.length > 0 && (
                    <span>{missingQty.length} 个计划项未填写计划数量，下达后对应批次数量为空</span>
                  )}
                  {missingBatchNo.length > 0 && (
                    <span>{missingBatchNo.length} 个计划项未填写批次号，下达时将自动生成</span>
                  )}
                </div>
              )}
              style={{ marginBottom: 12 }}
            />
          )}

          <Table<PlanItem>
            dataSource={sortedItems}
            columns={columns}
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 812, y: 360 }}
          />

          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--color-steel)' }}>
            下达后将按计划项生成 {sortedItems.length} 个生产批次，并锁定当前工艺路线版本。
          </div>
        </>
      )}
    </Modal>
  )
}
