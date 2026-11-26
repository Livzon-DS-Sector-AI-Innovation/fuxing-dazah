'use client'

// 编辑离职办理基本信息：仅「待发起审批 / 离职审批中（没有进行中的飞书审批）」可用。
// 弹窗销毁重建：Form 只在打开后才挂载，表单方法也只在打开后调用，不触发「useForm 未连接」警告。

import { useState } from 'react'
import { App as AntdApp, DatePicker, Form, Input, Modal, Select, Switch } from 'antd'
import dayjs from 'dayjs'
import type { OffboardingCaseDetail } from '@/types/hr'
import { updateOffboardingCase } from '@/actions/hr'
import { OFFBOARDING_CASE_TYPE_OPTIONS } from '@/lib/hr'

interface FormValues {
  offboarding_date: dayjs.Dayjs
  offboarding_type: string
  reason?: string
  application_submitted: boolean
  health_check_required?: boolean
  remark?: string
}

export default function CaseEditModal({
  open,
  detail,
  onClose,
  onSaved,
}: {
  open: boolean
  detail: OffboardingCaseDetail
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)
  const canEditHealthCheck = detail.status === 'draft'

  const submit = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return // 校验失败：表单已就地提示
    }
    setSaving(true)
    try {
      await updateOffboardingCase(detail.id, {
        offboarding_date: values.offboarding_date.format('YYYY-MM-DD'),
        offboarding_type: values.offboarding_type,
        // 传空串 = 清空（后端把 null 视为「不修改」）
        reason: values.reason?.trim() ?? '',
        application_submitted: values.application_submitted,
        ...(canEditHealthCheck ? { health_check_required: values.health_check_required } : {}),
        remark: values.remark?.trim() ?? '',
      })
      message.success('已保存')
      onClose()
      await onSaved()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title="编辑基本信息"
      okText="保存"
      cancelText="取消"
      onOk={() => void submit()}
      onCancel={onClose}
      confirmLoading={saving}
      destroyOnHidden
      width={520}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        initialValues={{
          offboarding_date: dayjs(detail.offboarding_date),
          offboarding_type: detail.offboarding_type,
          reason: detail.reason ?? '',
          application_submitted: detail.application_submitted,
          health_check_required: detail.health_check_required,
          remark: detail.remark ?? '',
        }}
      >
        <Form.Item
          name="offboarding_date"
          label="离职日期"
          rules={[{ required: true, message: '请选择离职日期' }]}
        >
          <DatePicker className="w-full" />
        </Form.Item>
        <Form.Item name="offboarding_type" label="离职类型" rules={[{ required: true }]}>
          <Select options={OFFBOARDING_CASE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
        </Form.Item>
        <Form.Item name="reason" label="离职原因" extra="会写入离职证明正文，请用规范表述">
          <Input.TextArea rows={2} maxLength={512} showCount />
        </Form.Item>
        <Form.Item name="application_submitted" label="是否已递交离职申请" valuePropName="checked">
          <Switch checkedChildren="已递交" unCheckedChildren="未递交" />
        </Form.Item>
        {canEditHealthCheck && (
          <Form.Item
            name="health_check_required"
            label="需完成离岗体检"
            valuePropName="checked"
            extra="重点岗位须先完成离岗体检登记才能发起审批；发起审批后不可再取消此项"
          >
            <Switch checkedChildren="需要" unCheckedChildren="不需要" />
          </Form.Item>
        )}
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={512} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}
