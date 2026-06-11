'use client'

import { useState } from 'react'
import { Modal, Form, Radio, Input, App, Tag, Descriptions } from 'antd'
import { verifyLevel } from '@/actions/safety'
import type { HazardReport } from '@/types/safety'
import {
  VERIFY_LEVEL_OPTIONS,
  VERIFY_LEVEL_STATUS_OPTIONS,
} from '@/types/safety'

const { TextArea } = Input

const LEVEL_REQUIREMENTS: Record<number, string> = {
  1: '确认整改是否按计划执行，现场是否改善',
  2: '确认整改措施有效性，是否需横向展开',
  3: '最终确认合规性，关闭隐患',
}

interface Props {
  open: boolean
  record: HazardReport | null
  onClose: () => void
  onSuccess: (updated: HazardReport) => void
}

export default function HazardVerifyModal({
  open,
  record,
  onClose,
  onSuccess,
}: Props) {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const { message } = App.useApp()

  // 自动确定当前复核级别
  const detectLevel = (): number => {
    if (!record) return 1
    const isGeneral = record.hazard_level === 'general'
    if (record.rectification_status === 'level2_approved') return 3
    // 一般隐患：一级通过后直接跳到三级
    if (record.rectification_status === 'level1_approved') return isGeneral ? 3 : 2
    if (record.rectification_status === 'replied') return 1
    return 1
  }

  const currentLevel = detectLevel()
  const levelLabel = VERIFY_LEVEL_OPTIONS.find((o) => o.value === currentLevel)?.label

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const response = await verifyLevel(record!.id, {
        level: currentLevel,
        action: values.action,
        opinion: values.opinion || undefined,
      })
      if (response.code === 200) {
        const actionLabel = values.action === 'approved' ? '通过' : '驳回'
        message.success(`${levelLabel}复核${actionLabel}`)
        onSuccess(response.data!)
        form.resetFields()
        onClose()
      } else {
        message.error(response.message || '复核失败')
      }
    } catch {
      // validation error
    } finally {
      setSubmitting(false)
    }
  }

  // 显示当前各级复核状态
  const renderVerifyStatus = (status: string) => {
    const opt = VERIFY_LEVEL_STATUS_OPTIONS.find((o) => o.value === status)
    return <Tag color={opt?.color}>{opt?.label || status}</Tag>
  }

  return (
    <Modal
      title={`${levelLabel}复核`}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={submitting}
      okText="提交复核"
      cancelText="取消"
      width={650}
      destroyOnHidden
    >
      {/* 隐患信息摘要 */}
      {record && (
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              background: '#faf9f7',
              padding: 12,
              borderRadius: 8,
              marginBottom: 12,
              fontSize: 13,
              lineHeight: 1.8,
            }}
          >
            <div>
              <strong>隐患编号：</strong>
              {record.hazard_no}
            </div>
            <div>
              <strong>隐患描述：</strong>
              {record.description}
            </div>
            <div>
              <strong>地点：</strong>
              {record.location || '-'}
            </div>
            <div>
              <strong>整改要求：</strong>
              {record.corrective_preventive_measures || '-'}
            </div>
          </div>

          {/* 整改回复内容 */}
          {record.rectification_reply && (
            <div
              style={{
                background: '#f0f7ff',
                padding: 12,
                borderRadius: 8,
                marginBottom: 12,
                fontSize: 13,
                lineHeight: 1.8,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>📝 整改回复</div>
              <div>{record.rectification_reply}</div>
              {record.rectification_replied_at && (
                <div style={{ color: '#999', marginTop: 4 }}>
                  回复时间：{record.rectification_replied_at}
                  {record.rectification_replied_by_name ? ` | 回复人：${record.rectification_replied_by_name}` : ''}
                </div>
              )}
            </div>
          )}

          {/* 三级复核进度 */}
          <Descriptions
            size="small"
            bordered
            column={3}
            style={{ fontSize: 12 }}
          >
            <Descriptions.Item label="一级复核">
              {renderVerifyStatus(record.verify_level_1_status || 'pending')}
            </Descriptions.Item>
            <Descriptions.Item label="二级复核">
              {renderVerifyStatus(record.verify_level_2_status || 'pending')}
            </Descriptions.Item>
            <Descriptions.Item label="三级复核">
              {renderVerifyStatus(record.verify_level_3_status || 'pending')}
            </Descriptions.Item>
          </Descriptions>
        </div>
      )}

      <div
        style={{
          background: '#fffbe6',
          border: '1px solid #ffe58f',
          padding: '8px 12px',
          borderRadius: 6,
          marginBottom: 16,
          fontSize: 13,
        }}
      >
        💡 {LEVEL_REQUIREMENTS[currentLevel]}
      </div>

      <Form form={form} layout="vertical" initialValues={{ level: currentLevel }}>
        <Form.Item name="level" label="复核级别" hidden>
          <Input />
        </Form.Item>
        <Form.Item
          name="action"
          label="复核结论"
          rules={[{ required: true, message: '请选择复核结论' }]}
        >
          <Radio.Group>
            <Radio value="approved">✅ 通过</Radio>
            <Radio value="rejected">❌ 驳回</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item name="opinion" label="复核意见">
          <TextArea rows={3} placeholder="请填写复核意见（可选）" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
