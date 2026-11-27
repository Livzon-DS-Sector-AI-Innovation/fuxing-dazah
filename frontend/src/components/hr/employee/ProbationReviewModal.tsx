'use client'

// 转正评估发起弹窗（三级审批链）：直属上级 → 部门经理 → 分管领导，审批人由系统自动解析。
// 从 EmployeeTable 拆出；syncMode 下仍开放——发送评估卡片不改写本地档案。

import { useState } from 'react'
import { App, Modal } from 'antd'
import { createProbationReview } from '@/actions/hr'
import { Employee } from '@/types/hr'

interface ProbationReviewModalProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
}

export default function ProbationReviewModal({ open, employee, onClose }: ProbationReviewModalProps) {
  const { message } = App.useApp()
  const [sending, setSending] = useState(false)

  const handleSend = async () => {
    if (!employee) return
    setSending(true)
    try {
      const r = await createProbationReview(employee.id)
      message.success(r.message || '评估卡片已发送给直属上级')
      onClose()
    } catch (e) { message.error(e instanceof Error ? e.message : '发起失败') }
    finally { setSending(false) }
  }

  return (
    <Modal title={`发起转正评估 — ${employee?.name || ''}`} open={open}
      onCancel={onClose}
      onOk={handleSend} okText="发送评估卡片" confirmLoading={sending}>
      {employee && (
        <div className="text-xs text-gray-500 mb-3">
          {employee.department} · {employee.position} ｜ 入职 {employee.hire_date?.slice(0, 10)}
          {employee.computed_probation_end && ` ｜ 转正到期 ${employee.computed_probation_end.slice(0, 10)}`}
          {employee.is_key_position ? ' ｜ 重点岗位（须有安全考试合格记录）' : ''}
        </div>
      )}
      <div className="rounded-md border border-[var(--color-hairline)] p-3 text-xs text-gray-600 space-y-1">
        <div>① 直属上级评估：{employee?.direct_manager_name || <span className="text-red-500">档案未登记直属上级，请先补录</span>}</div>
        <div>② 部门经理审批、③ 分管领导审批：按部门管理中配置的负责人/分管领导自动解析</div>
        <div className="text-gray-400">三级全部同意后自动转正生效（写源表「员工性质=正式」）。</div>
      </div>
    </Modal>
  )
}
