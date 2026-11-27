'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { App, Input } from 'antd'

import {
  approveHardwareScrapClient,
  cancelHardwareScrapClient,
  executeHardwareScrapClient,
  rejectHardwareScrapClient,
  submitHardwareScrapClient,
} from '@/lib/api/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'

/**
 * 报废单状态流转（「申请单据」与「台账 → 报废」两个页面共用）。
 *
 * 与领料单同一条出库路径：提交即预扣 → 审批人通过（平台）→ 仓管出库实扣；
 * 驳回/撤回释放预扣。操作人一律取当前登录用户（后端按登录态落
 * approved_by / executed_by），前端不再传写死的称呼。
 */
export function useScrapActions() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:scrap:manage')

  // 报废单状态变化会影响预扣/在手（stock、summary）、申请单据合并列表与统计卡、
  // 台账报废列表，统一失效
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware'] })
    queryClient.invalidateQueries({ queryKey: ['hardware-scraps'] })
    queryClient.invalidateQueries({ queryKey: ['hardware-scrap'] })
  }
  const onError = (e: Error) => message.error(e.message)

  const submitMut = useMutation({
    mutationFn: (id: string) => submitHardwareScrapClient(id),
    onSuccess: (s) => {
      message.success(
        s.approval_channel === 'feishu'
          ? '已提交（预扣生效），飞书审批单已发给所选审批人'
          : '已提交（预扣生效），等审批人在平台点通过',
      )
      invalidate()
    },
    onError,
  })
  const approveMut = useMutation({
    mutationFn: (id: string) => approveHardwareScrapClient(id),
    onSuccess: () => {
      message.success('已审批通过（预扣保持，待仓管出库）')
      invalidate()
    },
    onError,
  })
  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectHardwareScrapClient(id, reason),
    onSuccess: () => {
      message.success('已驳回（预扣已释放）')
      invalidate()
    },
    onError,
  })
  const executeMut = useMutation({
    mutationFn: (id: string) => executeHardwareScrapClient(id),
    onSuccess: () => {
      message.success('出库完成，库存已扣减并记录流水')
      invalidate()
    },
    onError,
  })
  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelHardwareScrapClient(id),
    onSuccess: () => {
      message.success('已撤回（预扣已释放）')
      invalidate()
    },
    onError,
  })

  const reject = (id: string) => {
    let reason = ''
    modal.warning({
      title: '驳回报废单',
      content: (
        <Input.TextArea
          rows={3}
          placeholder="驳回原因"
          onChange={(e) => {
            reason = e.target.value
          }}
        />
      ),
      okText: '确认驳回',
      okButtonProps: { danger: true },
      onOk: () => rejectMut.mutate({ id, reason: reason.trim() || '未填写原因' }),
    })
  }

  const cancel = (id: string) => {
    modal.confirm({
      title: '撤回报废单',
      width: 420,
      okText: '确认撤回',
      content: (
        <div className="text-[13px]">撤回后释放预扣；如仍需报废请重新发起。</div>
      ),
      onOk: () => cancelMut.mutate(id),
    })
  }

  return {
    /** 「报废管理」权限：提交、出库、撤回 */
    canManage,
    submit: (id: string) => submitMut.mutate(id),
    /** 平台点通过（资格由后端按报废管理权限或所选审批人校验） */
    approve: (id: string) => approveMut.mutate(id),
    reject,
    cancel,
    execute: (id: string) => executeMut.mutate(id),
    executing: executeMut.isPending,
  }
}

export type ScrapActions = ReturnType<typeof useScrapActions>
