'use client'

import { useState } from 'react'
import { App, Input, Modal } from 'antd'

import { submitURsAppeal } from '@/actions/safety'
import { T } from '../shared-styles'

interface Props {
  recordId: string | null
  onClose: () => void
  onSuccess?: () => void
}

export function URSAppealModal({ recordId, onClose, onSuccess }: Props) {
  const { message } = App.useApp()
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleOk = async () => {
    if (!recordId || !reason.trim()) {
      message.warning('请填写申诉理由')
      return
    }
    setSubmitting(true)
    const res = await submitURsAppeal(recordId, reason.trim())
    setSubmitting(false)
    if (res.code >= 200 && res.code < 300) {
      message.success('申诉已受理，正在重新评估')
      onSuccess?.()
      onClose()
    } else message.error(res.message || '提交失败')
  }

  return (
    <Modal title="提交申诉" open={!!recordId} onCancel={onClose} onOk={handleOk} confirmLoading={submitting}
      okText="确认申诉" okButtonProps={{ style: { background: T.primary, borderColor: T.primary } }}>
      <p style={{ color: '#787671', fontSize: 13 }}>对已驳回的 URS 审核结论提交申诉，系统将重新评估风险画像与标准适配。</p>
      <Input.TextArea rows={4} placeholder="请填写申诉理由（如：该设备位于洁净区，不涉及防爆要求）" value={reason} onChange={(e) => setReason(e.target.value)} />
    </Modal>
  )
}
