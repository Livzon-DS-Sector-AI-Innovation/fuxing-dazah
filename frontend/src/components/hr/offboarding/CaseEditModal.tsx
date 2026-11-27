'use client'

// 编辑离职办理基本信息：仅「待发起审批 / 离职审批中（没有进行中的飞书审批）」可用。
// 弹窗销毁重建：Form 只在打开后才挂载，表单方法也只在打开后调用，不触发「useForm 未连接」警告。

import { useState } from 'react'
import { App as AntdApp, DatePicker, Form, Input, Modal, Radio, Select } from 'antd'
import dayjs from 'dayjs'
import type { OffboardingCaseDetail } from '@/types/hr'
import { updateOffboardingCase } from '@/actions/hr'
import { OFFBOARDING_CASE_TYPE_OPTIONS } from '@/lib/hr'

const YES_NO = [
  { label: '已递交', value: true },
  { label: '未递交', value: false },
]
const NEED_NO = [
  { label: '需要', value: true },
  { label: '不需要', value: false },
]

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
  // 台账行来自飞书同步：离职日期与类型以飞书表为准，这里不改（改了也会被整点同步改回）
  const ledgerSynced = !!detail.ledger_synced

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
        ...(ledgerSynced ? {} : {
          offboarding_date: values.offboarding_date?.format('YYYY-MM-DD'),
          offboarding_type: values.offboarding_type,
        }),
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
        {ledgerSynced ? (
          <>
            <Form.Item label="离职日期" extra="来自飞书离职表，以飞书表为准；要改请到飞书表修改">
              <Input readOnly value={detail.offboarding_date} />
            </Form.Item>
            <Form.Item label="离职类型" extra="来自飞书离职表，以飞书表为准">
              <Input readOnly value={detail.offboarding_type} />
            </Form.Item>
          </>
        ) : (
          <>
            <Form.Item
              name="offboarding_date"
              label="离职日期"
              rules={[{ required: true, message: '请选择离职日期' }]}
            >
              <DatePicker className="w-full" />
            </Form.Item>
            <Form.Item name="offboarding_type" label="离职类型" rules={[{ required: true, message: '请选择离职类型' }]}>
              <Select options={OFFBOARDING_CASE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
            </Form.Item>
          </>
        )}
        <Form.Item name="reason" label="离职原因" extra="会写入离职证明正文，请用规范表述">
          <Input.TextArea rows={2} maxLength={512} showCount />
        </Form.Item>
        <Form.Item name="application_submitted" label="是否已递交离职申请">
          <Radio.Group optionType="button" options={YES_NO} />
        </Form.Item>
        {canEditHealthCheck && (
          <Form.Item
            name="health_check_required"
            label="需完成离岗体检"
            extra="重点岗位须先完成离岗体检登记才能提交审批；提交审批后不可再取消此项"
          >
            <Radio.Group optionType="button" options={NEED_NO} />
          </Form.Item>
        )}
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} maxLength={512} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}
