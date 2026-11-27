'use client'

import { Button, Space } from 'antd'

import type { HardwareScrapRecord } from '@/types/warehouse-hardware'
import type { ScrapActions } from './useScrapActions'

/**
 * 报废单行内操作（「申请单据」与「台账 → 报废」共用），按钮位置与领料单一致：
 * 待审批 → 通过 / 驳回；待出库 → 出库；草稿 → 提交审批。
 */
export function ScrapRowActions({
  scrap,
  actions,
  onDetail,
  onExecute,
}: {
  scrap: HardwareScrapRecord
  actions: ScrapActions
  onDetail: (id: string) => void
  onExecute: (id: string) => void
}) {
  const { canManage } = actions
  return (
    <Space wrap size={4}>
      <Button size="small" onClick={() => onDetail(scrap.id)}>
        明细
      </Button>
      {/* 审批人在平台点通过（与飞书审批单任选其一）；资格由后端 can_approve 给出 */}
      {scrap.status === 'pending' && scrap.can_approve && (
        <>
          <Button size="small" type="primary" onClick={() => actions.approve(scrap.id)}>
            通过
          </Button>
          <Button size="small" danger onClick={() => actions.reject(scrap.id)}>
            驳回
          </Button>
        </>
      )}
      {scrap.status === 'approved' && canManage && (
        <Button size="small" type="primary" danger onClick={() => onExecute(scrap.id)}>
          出库
        </Button>
      )}
      {scrap.status === 'draft' && canManage && (
        <Button size="small" type="primary" onClick={() => actions.submit(scrap.id)}>
          提交审批
        </Button>
      )}
      {(scrap.status === 'draft' || scrap.status === 'pending') && canManage && (
        <Button size="small" onClick={() => actions.cancel(scrap.id)}>
          取消
        </Button>
      )}
    </Space>
  )
}
