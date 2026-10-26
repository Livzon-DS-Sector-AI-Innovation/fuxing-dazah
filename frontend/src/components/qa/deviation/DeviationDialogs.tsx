'use client'

import { useState } from 'react'
import { Alert, App, DatePicker, Form, Input, Modal } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { extendDeviation, transitionDeviation } from '@/actions/qa-deviation'
import { DEVIATION_ACTION_LABEL, type DeviationDetail, type DeviationTransitionAction } from '@/types/qa-deviation'
import { actionError } from './shared'

const TRANSITION_HINT: Record<DeviationTransitionAction, string> = {
  start_investigation: '进入调查阶段后可填写人机料法环分析、5Why 与根本原因。',
  submit_assessment: '调查结论将锁定为评估依据；评估阶段填写质量影响、分类与 CAPA 决定。',
  close: '关闭后偏差所有内容将锁定不可编辑，CAPA 可继续独立跟踪。',
}

/** 推进偏差状态：开始调查 / 提交评估 / 关闭，备注写入流转日志。 */
export function TransitionModal({
  deviation,
  action,
  onClose,
  onDone,
}: {
  deviation: DeviationDetail
  action: DeviationTransitionAction | null
  onClose: () => void
  onDone: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<{ comment?: string }>()
  const [submitting, setSubmitting] = useState(false)

  const handleOk = async () => {
    if (!action) return
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = await transitionDeviation(deviation.id, action, values.comment?.trim() || undefined)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(`${DEVIATION_ACTION_LABEL[action]}成功`)
      form.resetFields()
      onDone()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={action ? DEVIATION_ACTION_LABEL[action] : ''}
      open={action !== null}
      onCancel={onClose}
      onOk={handleOk}
      okText={action ? DEVIATION_ACTION_LABEL[action] : '确定'}
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
    >
      {action && (
        <Alert
          type={action === 'close' ? 'warning' : 'info'}
          showIcon
          title={TRANSITION_HINT[action]}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form form={form} layout="vertical">
        <Form.Item name="comment" label="备注（记入流转日志）">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={2000} placeholder="例如：质量负责人已批准关闭" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 延长关闭期限：新期限必须晚于当前期限，原因必填并进入流转日志。 */
export function ExtendModal({
  deviation,
  open,
  onClose,
  onDone,
}: {
  deviation: DeviationDetail
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<{ new_due_date: Dayjs; reason: string }>()
  const [submitting, setSubmitting] = useState(false)
  const currentDue = dayjs(deviation.due_date)

  const handleOk = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = await extendDeviation(deviation.id, values.new_due_date.format('YYYY-MM-DD'), values.reason.trim())
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('关闭期限已延长')
      form.resetFields()
      onDone()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="延长关闭期限"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="确认延期"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        title={`当前关闭期限 ${currentDue.format('YYYY-MM-DD')}，已延期 ${deviation.extension_count} 次`}
        description="SOP 要求偏差自发现之日起 30 天内关闭；预计无法完成时应提前发起延期并说明原因。"
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical">
        <Form.Item
          name="new_due_date"
          label="新的关闭期限"
          rules={[{ required: true, message: '请选择新期限' }]}
        >
          <DatePicker style={{ width: '100%' }} disabledDate={(date) => !date.isAfter(currentDue, 'day')} />
        </Form.Item>
        <Form.Item name="reason" label="延期原因" rules={[{ required: true, whitespace: true, message: '请填写延期原因' }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={2000} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
