'use client'

// 持证到期预警 — 回填抽屉（CertRenewDrawer）
// 根据 cert_category 显示不同字段：
//   special_op → next_review_date（再复审时间）
//   guardian_a / guardian_b → renewed_date（已换证日期）
//   notes（可选备注）
// 提交 → renewCertificate(id, body) → 成功后回调 onSaved 刷新列表。

import { useEffect, useState } from 'react'
import { App, Button, DatePicker, Drawer, Form, Input, Space, Typography } from 'antd'
import dayjs from 'dayjs'
import { renewCertificate } from '@/actions/safety'
import type { CertWarningDetail } from '@/types/safety'
import { CERT_CATEGORY_UI, T, UI } from './certWarningConstants'

const { Text } = Typography
const { TextArea } = Input

type RenewRequestBody = {
  next_review_date?: string | null
  renewed_date?: string | null
  notes?: string
}

interface CertRenewDrawerProps {
  open: boolean
  onClose: () => void
  record: CertWarningDetail | null
  onSaved: () => void
}

export default function CertRenewDrawer({ open, onClose, record, onSaved }: CertRenewDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const isSpecialOp = record?.cert_category === 'special_op'
  const isGuardian = record && (record.cert_category === 'guardian_a' || record.cert_category === 'guardian_b')

  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (record) {
      form.setFieldsValue({
        next_review_date: isSpecialOp ? null : undefined,
        renewed_date: isGuardian ? null : undefined,
        notes: record.notes ?? '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, record?.id])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const body: RenewRequestBody = {
        notes: (values.notes ?? '').trim() || undefined,
      }
      if (isSpecialOp) {
        body.next_review_date = values.next_review_date ? values.next_review_date.format('YYYY-MM-DD') : null
      } else {
        body.renewed_date = values.renewed_date ? values.renewed_date.format('YYYY-MM-DD') : null
      }
      const res = await renewCertificate(record!.id, body)
      if (res.code === 200) {
        message.success('回填成功，预警状态已刷新')
        onSaved()
      } else {
        message.error(res.message || '回填失败')
      }
    } catch {
      // validation error
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="回填复审/换证结果"
      width={440}
      open={open}
      onClose={onClose}
      destroyOnHidden
      footer={
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            确认回填
          </Button>
        </Space>
      }
    >
      {record && (
        <div
          style={{
            background: T.surface,
            border: `1px solid ${T.hairline}`,
            borderRadius: 8,
            padding: '10px 14px',
            marginBottom: 16,
            fontSize: 13,
            lineHeight: 1.8,
          }}
        >
          <div>
            <b>人员：</b>
            {record.person_name || '-'} ｜ <b>证件：</b>
            {CERT_CATEGORY_UI[record.cert_category]?.label ?? record.cert_category} ｜ <b>节点：</b>
            {record.current_node || '-'}
          </div>
          <div>
            <b>截止日期：</b>
            {record.deadline || '-'} ｜ <b>剩余天数：</b>
            {record.remaining_days != null ? record.remaining_days : '-'} ｜ <b>建议：</b>
            {record.suggestion || '-'}
          </div>
        </div>
      )}

      <Form form={form} layout="vertical">
        {isSpecialOp && (
          <Form.Item name="next_review_date" label="再复审时间" rules={[{ required: true, message: '请选择再复审时间' }]}>
            <DatePicker style={{ width: '100%' }} placeholder="选择新的再复审时间" />
          </Form.Item>
        )}
        {isGuardian && (
          <Form.Item name="renewed_date" label="已换证日期" rules={[{ required: true, message: '请选择已换证日期' }]}>
            <DatePicker style={{ width: '100%' }} placeholder="选择已换证日期" />
          </Form.Item>
        )}
        <Form.Item name="notes" label="备注">
          <TextArea rows={3} placeholder="可填写复审/换证完成情况等备注（可选）" />
        </Form.Item>
        {isGuardian && (
          <Text style={{ color: UI.muted, fontSize: 12, display: 'block', marginBottom: 8 }}>
            回填后系统将以已换证日期为新起算点进入下一证件周期，自动重算复审及换证时间。
          </Text>
        )}
        {isSpecialOp && (
          <Text style={{ color: UI.muted, fontSize: 12, display: 'block', marginBottom: 8 }}>
            回填新再复审时间后，系统将重新计算剩余天数并刷新预警状态。
          </Text>
        )}
      </Form>
    </Drawer>
  )
}

