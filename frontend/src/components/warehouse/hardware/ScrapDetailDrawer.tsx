'use client'

import { useQuery } from '@tanstack/react-query'
import { Descriptions, Drawer, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'

import { fetchHardwareScrapClient } from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_SCRAP_REASON_LABEL,
  HARDWARE_SCRAP_STATUS_LABEL,
  type HardwareScrapRecord,
} from '@/types/warehouse-hardware'
import { StatusTag } from '@/components/warehouse'
import { SCRAP_STATUS_TONE } from './constants'
import { formatQty } from './format'

function fmtTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'
}

function channelLabel(s: HardwareScrapRecord): string {
  if (s.approval_channel === 'feishu') {
    return `飞书「福兴电子领/退料单审批」${
      s.approval_instance_code ? `（实例 ${s.approval_instance_code}）` : ''
    }`
  }
  if (s.approval_channel === 'manual') return '平台审批（未配置飞书分支）'
  return '—'
}

/** 报废单详情（「申请单据」与「台账 → 报废」共用）：按单号取最新详情，明细始终完整。 */
export function ScrapDetailDrawer({
  scrapId,
  onClose,
}: {
  scrapId: string | null
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['hardware-scrap', scrapId],
    queryFn: () => fetchHardwareScrapClient(scrapId!),
    enabled: !!scrapId,
  })
  const scrap = data ?? null

  return (
    <Drawer
      title={scrap ? `报废单 ${scrap.scrap_no}` : '报废单详情'}
      open={!!scrapId}
      onClose={onClose}
      width={640}
      loading={isLoading && !!scrapId}
    >
      {scrap && (
        <div className="space-y-3">
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="报废条件">
              {HARDWARE_SCRAP_REASON_LABEL[scrap.scrap_reason] ?? scrap.scrap_reason}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <StatusTag
                tone={SCRAP_STATUS_TONE[scrap.status] ?? 'default'}
                label={HARDWARE_SCRAP_STATUS_LABEL[scrap.status] ?? scrap.status}
              />
            </Descriptions.Item>
            <Descriptions.Item label="发起">
              {scrap.dept_name} / {scrap.requested_by}
            </Descriptions.Item>
            <Descriptions.Item label="发起时间">{fmtTime(scrap.created_at)}</Descriptions.Item>
            <Descriptions.Item label="说明" span={2}>
              {scrap.reason_note || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="审批人">{scrap.approver_name || '—'}</Descriptions.Item>
            <Descriptions.Item label="审批通道">{channelLabel(scrap)}</Descriptions.Item>
            <Descriptions.Item label="审批通过">
              {scrap.approved_by ? `${scrap.approved_by}　${fmtTime(scrap.approved_at)}` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="出库">
              {scrap.executed_by ? `${scrap.executed_by}　${fmtTime(scrap.scrapped_at)}` : '—'}
            </Descriptions.Item>
          </Descriptions>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={scrap.items ?? []}
            columns={[
              { title: '品名', dataIndex: 'name' },
              { title: '规格', dataIndex: 'spec', render: (v) => v || '—' },
              { title: '单位', dataIndex: 'unit', width: 60, render: (v) => v || '—' },
              {
                title: '报废数量',
                dataIndex: 'quantity',
                width: 90,
                align: 'right',
                render: (v: unknown) => formatQty(v),
              },
              {
                title: '批次',
                dataIndex: 'preferred_lot_id',
                width: 110,
                render: (v) => (v ? '指定批次' : '先进先出'),
              },
            ] as TableColumnsType<NonNullable<HardwareScrapRecord['items']>[number]>}
          />
          {scrap.lot_allocations && scrap.lot_allocations.length > 0 && (
            <div className="text-[12px] text-[var(--color-steel)]">
              出库批次：
              {scrap.lot_allocations
                .map((a) => `${String(a.lot_no ?? '')}×${formatQty(a.qty)}`)
                .join('，')}
            </div>
          )}
          {scrap.rejected_reason && (
            <div className="text-[13px] text-red-600">驳回原因：{scrap.rejected_reason}</div>
          )}
          {scrap.remark && <div className="text-[12px] text-gray-500">备注：{scrap.remark}</div>}
        </div>
      )}
    </Drawer>
  )
}
