'use client'

// 异常随访 Modal（OhFollowupModal）— 处置 + 手动补录双模式
// followup != null → 处置模式：Form（action_taken 必填 / responsible / followup_date / 状态 open→followed）
//   + 底部危险区「关闭随访」（Popconfirm → closeOhFollowup，关闭需填写 action_taken）；
// followup == null → 手动补录模式（createOhFollowup，preset 预填 person_name/exam_id）。

import { useEffect, useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Typography,
} from 'antd'
import dayjs from 'dayjs'
import { closeOhFollowup, createOhFollowup, updateOhFollowup } from '@/actions/safety'
import type { OhFollowup } from '@/types/safety'
import {
  OH_FOLLOWUP_TYPE_FILTER,
  OH_INDICATOR_CATEGORY_FILTER,
  OH_SEVERITY_UI,
  T,
  UI,
} from './ohConstants'

const { Text } = Typography
const { TextArea } = Input

interface OhFollowupModalProps {
  open: boolean
  onClose: () => void
  followup: OhFollowup | null
  preset?: {
    person_name?: string
    exam_id?: string
  }
  onSaved: () => void
}

export default function OhFollowupModal({
  open,
  onClose,
  followup,
  preset,
  onSaved,
}: OhFollowupModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [closing, setClosing] = useState(false)

  const isDispose = followup != null

  useEffect(() => {
    if (!open) return
    if (isDispose && followup) {
      form.setFieldsValue({
        action_taken: followup.action_taken ?? '',
        responsible: followup.responsible ?? '',
        followup_date: followup.followup_date ? dayjs(followup.followup_date) : null,
        status: 'followed',
      })
    } else {
      form.resetFields()
      form.setFieldsValue({
        person_name: preset?.person_name ?? '',
        indicator_name: '',
        indicator_value: '',
        reference_range: '',
        category: undefined,
        abnormal_level: undefined,
        followup_type: undefined,
        followup_date: null,
        responsible: '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, followup?.id])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (isDispose && followup) {
        const res = await updateOhFollowup(followup.id, {
          action_taken: values.action_taken.trim(),
          responsible: values.responsible?.trim() || undefined,
          followup_date: values.followup_date ? values.followup_date.format('YYYY-MM-DD') : undefined,
          status: values.status,
        })
        if (res.code === 200) {
          message.success('处置已提交')
          onSaved()
        } else {
          message.error(res.message || '提交失败')
        }
      } else {
        const res = await createOhFollowup({
          exam_id: preset?.exam_id || undefined,
          person_name: (values.person_name ?? preset?.person_name ?? '').trim() || undefined,
          indicator_name: values.indicator_name.trim(),
          indicator_value: values.indicator_value?.trim() || undefined,
          reference_range: values.reference_range?.trim() || undefined,
          category: values.category || undefined,
          abnormal_level: values.abnormal_level || undefined,
          followup_type: values.followup_type || undefined,
          followup_date: values.followup_date ? values.followup_date.format('YYYY-MM-DD') : undefined,
          responsible: values.responsible?.trim() || undefined,
        })
        if (res.code === 200) {
          message.success('随访已补录')
          onSaved()
        } else {
          message.error(res.message || '补录失败')
        }
      }
    } catch {
      // validation error
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = async () => {
    if (!followup) return
    const actionTaken = form.getFieldValue('action_taken')?.trim()
    if (!actionTaken) {
      message.warning('关闭随访需先填写处置措施（action_taken）')
      return
    }
    setClosing(true)
    try {
      const res = await closeOhFollowup(followup.id, actionTaken)
      if (res.code === 200) {
        message.success('随访已关闭')
        onSaved()
      } else {
        message.error(res.message || '关闭失败')
      }
    } finally {
      setClosing(false)
    }
  }

  return (
    <Modal
      title={isDispose ? '处置异常随访' : '手动补录随访'}
      open={open}
      onCancel={onClose}
      width={620}
      destroyOnHidden
      footer={
        <Space>
          {isDispose && (
            <Popconfirm
              title="关闭随访"
              description="关闭后该随访闭环（记 closed_at），需已填写处置措施"
              okText="确认关闭" cancelText="取消" okButtonProps={{ danger: true }}
              onConfirm={handleClose}
            >
              <Button danger loading={closing}>关闭随访</Button>
            </Popconfirm>
          )}
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            {isDispose ? '提交处置' : '确认补录'}
          </Button>
        </Space>
      }
    >
      {isDispose && followup && (
        <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, lineHeight: 1.8 }}>
          <div><b>人员：</b>{followup.person_name || '-'} ｜ <b>指标：</b>{followup.indicator_name || '-'} {followup.indicator_value ? `(${followup.indicator_value})` : ''}</div>
          <div><b>建议复查日期：</b>{followup.followup_date || '-'}</div>
        </div>
      )}

      <Form form={form} layout="vertical">
        {!isDispose && (
          <Form.Item name="person_name" label="人员姓名" rules={[{ required: true, message: '请填写人员姓名' }]}>
            <Input placeholder="人员姓名" disabled={!!preset?.person_name} />
          </Form.Item>
        )}
        <Form.Item name="indicator_name" label="异常指标" rules={[{ required: true, message: '请填写异常指标' }]}>
          <Input placeholder="如：白细胞计数" />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item name="indicator_value" label="指标数值">
            <Input placeholder="如：3.2×10⁹/L ↓" />
          </Form.Item>
          <Form.Item name="reference_range" label="参考范围">
            <Input placeholder="如：4-10×10⁹/L" />
          </Form.Item>
          <Form.Item name="category" label="指标类别">
            <Select options={OH_INDICATOR_CATEGORY_FILTER.filter((o) => o.value !== '')} placeholder="选择类别" allowClear />
          </Form.Item>
          <Form.Item name="abnormal_level" label="异常程度">
            <Select
              placeholder="选择程度"
              allowClear
              options={Object.entries(OH_SEVERITY_UI).map(([value, ui]) => ({ value, label: ui.label }))}
            />
          </Form.Item>
        </div>
        <Form.Item name="followup_type" label="随访类型">
          <Select options={OH_FOLLOWUP_TYPE_FILTER.filter((o) => o.value !== '')} placeholder="选择随访类型" allowClear />
        </Form.Item>
        <Form.Item name="followup_date" label="建议复查日期">
          <DatePicker style={{ width: '100%' }} placeholder="选择日期" />
        </Form.Item>
        <Form.Item name="responsible" label="责任人">
          <Input placeholder="责任人" />
        </Form.Item>
        <Form.Item
          name="action_taken"
          label="处置措施"
          rules={[{ required: true, message: '请填写处置措施' }]}
          extra={isDispose ? <Text style={{ color: UI.muted, fontSize: 12 }}>提交后状态自动流转为「已处置待闭环」；关闭随访需已填写此字段</Text> : undefined}
        >
          <TextArea rows={3} placeholder="请描述处置措施（复查安排、转诊、调岗建议等）" />
        </Form.Item>
        {isDispose && (
          <Form.Item name="status" label="状态迁移">
            <Select
              options={[
                { value: 'followed', label: '已处置待闭环' },
                { value: 'open', label: '保持待处置' },
              ]}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
