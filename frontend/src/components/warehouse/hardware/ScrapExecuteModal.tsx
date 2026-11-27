'use client'

import { useQuery } from '@tanstack/react-query'
import { Modal, Table } from 'antd'
import type { TableColumnsType } from 'antd'

import { fetchHardwareScrapClient, fetchHardwareStockDetailClient } from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_SCRAP_REASON_LABEL,
  type HardwareScrapRecord,
} from '@/types/warehouse-hardware'
import { StatusTag } from '@/components/warehouse'
import { formatQty } from './format'

/**
 * 报废出库确认（照发料弹窗 IssueModal）：展示明细与先进先出的建议批次，
 * 仓管确认后才实扣——这是报废出库路径上唯一动账的一步。
 */
export function ScrapExecuteModal({
  scrapId,
  loading,
  onConfirm,
  onClose,
}: {
  scrapId: string | null
  loading: boolean
  onConfirm: (id: string) => void
  onClose: () => void
}) {
  const { data: scrap } = useQuery({
    queryKey: ['hardware-scrap', scrapId],
    queryFn: () => fetchHardwareScrapClient(scrapId!),
    enabled: !!scrapId,
  })
  const materialIds = scrap?.items?.map((i) => i.material_id) ?? []
  const { data: stockByMaterial } = useQuery({
    queryKey: ['warehouse', 'hardware', 'scrap-out-lots', materialIds.join(',')],
    queryFn: async () => {
      const entries = await Promise.all(
        materialIds.map(async (mid) => {
          const detail = await fetchHardwareStockDetailClient(mid)
          return [mid, detail.lots] as const
        }),
      )
      return Object.fromEntries(entries)
    },
    enabled: materialIds.length > 0 && !!scrap,
  })

  return (
    <Modal
      title={scrap ? `出库确认 · ${scrap.scrap_no}` : '出库确认'}
      open={!!scrapId}
      onCancel={onClose}
      onOk={() => scrap && onConfirm(scrap.id)}
      confirmLoading={loading}
      okText="确认出库（实扣）"
      okButtonProps={{ danger: true, disabled: !scrap?.items?.length }}
      width={700}
    >
      {scrap && (
        <>
          <div className="mb-3 text-[13px] leading-6">
            <div>
              发起：{scrap.dept_name} / {scrap.requested_by}　审批人：
              {scrap.approved_by || scrap.approver_name || '-'}
            </div>
            <div>
              报废条件：{HARDWARE_SCRAP_REASON_LABEL[scrap.scrap_reason] ?? scrap.scrap_reason}
              {scrap.reason_note ? `　说明：${scrap.reason_note}` : ''}
            </div>
          </div>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={scrap.items ?? []}
            columns={[
              { title: '物料', dataIndex: 'name', width: 180 },
              { title: '规格', dataIndex: 'spec', width: 110, render: (v) => v || '-' },
              {
                title: '报废数量',
                dataIndex: 'quantity',
                width: 90,
                align: 'right',
                className: 'tabular-nums',
                render: (v: unknown) => formatQty(v),
              },
              {
                title: '建议批次（先进先出）',
                render: (_: unknown, r) => {
                  const lots = stockByMaterial?.[r.material_id] ?? []
                  const usable = lots.filter((l) => Number(l.remaining_quantity) > 0)
                  if (!usable.length) return <StatusTag tone="danger" label="无可用批次" />
                  return (
                    <span className="font-mono text-[12px]">
                      {usable
                        .slice(0, 3)
                        .map((l) => `${l.lot_no}(${formatQty(l.remaining_quantity)})`)
                        .join(' → ')}
                    </span>
                  )
                },
              },
            ] as TableColumnsType<NonNullable<HardwareScrapRecord['items']>[number]>}
          />
        </>
      )}
    </Modal>
  )
}
