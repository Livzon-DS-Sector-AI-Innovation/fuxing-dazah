'use client'

// 转正评估发起弹窗：评估卡片私发部门负责人（飞书），结论经 HR 在档案页「转正管理」面板确认生效。
// 从 EmployeeTable 拆出；syncMode 下仍开放——发送评估卡片不改写本地档案。

import { useEffect, useRef, useState } from 'react'
import { App, Modal, Select } from 'antd'
import { createProbationReview, fetchEmployeesAction } from '@/actions/hr'
import { Employee } from '@/types/hr'

interface ProbationReviewModalProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
}

export default function ProbationReviewModal({ open, employee, onClose }: ProbationReviewModalProps) {
  const { message } = App.useApp()
  const [reviewer, setReviewer] = useState<string | undefined>(undefined)
  const [reviewerOptions, setReviewerOptions] = useState<{ value: string; label: string }[]>([])
  const [searching, setSearching] = useState(false)
  const [sending, setSending] = useState(false)
  const seqRef = useRef(0)

  // 评估人远程搜索：请求序号守卫丢弃过期响应（慢请求晚归不得覆盖新结果）
  const searchReviewers = async (keyword: string) => {
    const seq = ++seqRef.current
    setSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== seqRef.current) return
      setReviewerOptions(d.data.map((e) => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || ''} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默 */ }
    finally { if (seq === seqRef.current) setSearching(false) }
  }

  // 打开即预载在职人员候选（部门负责人通常在首页）
  useEffect(() => {
    if (open) searchReviewers('')
  }, [open])

  const handleClose = () => {
    onClose()
    setReviewer(undefined)
  }

  const handleSend = async () => {
    if (!employee || !reviewer) { message.warning('请选择评估人'); return }
    setSending(true)
    try {
      const r = await createProbationReview(employee.id, reviewer)
      message.success(r.message || '评估卡片已发送')
      handleClose()
    } catch (e) { message.error(e instanceof Error ? e.message : '发起失败') }
    finally { setSending(false) }
  }

  return (
    <Modal title={`发起转正评估 — ${employee?.name || ''}`} open={open}
      onCancel={handleClose}
      onOk={handleSend} okText="发送评估卡片" confirmLoading={sending}
      okButtonProps={{ disabled: !reviewer }}>
      {employee && (
        <div className="text-xs text-gray-500 mb-3">
          {employee.department} · {employee.position} ｜ 入职 {employee.hire_date?.slice(0, 10)}
          {employee.computed_probation_end && ` ｜ 转正到期 ${employee.computed_probation_end.slice(0, 10)}`}
        </div>
      )}
      <Select style={{ width: '100%' }} placeholder="搜索并选择评估人（部门负责人）"
        showSearch filterOption={false} onSearch={searchReviewers}
        notFoundContent={searching ? <span style={{ fontSize: 12 }}>搜索中…</span> : null}
        value={reviewer} onChange={setReviewer} options={reviewerOptions} />
      <div className="text-xs text-gray-400 mt-3">
        评估表单卡片将私发至负责人飞书（需其登录过系统或在源表有员工账号）；结论提交后由 HR 在档案页「转正管理」确认生效。
      </div>
    </Modal>
  )
}
