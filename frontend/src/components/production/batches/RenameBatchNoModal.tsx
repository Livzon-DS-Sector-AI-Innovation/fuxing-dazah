'use client'

import { useState } from 'react'
import { Alert, App, Form, Input, Modal } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { renameBatchNo } from '@/actions/production'

interface Props {
  batchId: string
  batchNo: string
  onClose: () => void
}

export function RenameBatchNoModal({ batchId, batchNo, onClose }: Props) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const newNo = ((values.batch_no as string) ?? '').trim()
    if (newNo === batchNo) {
      message.info('批次号未变化')
      return
    }
    setSubmitting(true)
    try {
      const result = await renameBatchNo(batchId, newNo)
      if (result.success) {
        message.success('批次号已修改')
        // 批号出现在详情标题、列表、溯源图与工作台，均实时读库需刷新
        queryClient.invalidateQueries({ queryKey: ['production-batch-detail', batchId] })
        queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        queryClient.invalidateQueries({ queryKey: ['production-trace'] })
        queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
        onClose()
      } else {
        message.error(result.error ?? '修改失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          修改批次号
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={520}
      okText="确认修改"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px' } }}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        title="修改将记录审计日志（修改人、原批号）。中间体产出记录里已固化的批号不受影响。"
      />
      <Form form={form} layout="vertical" initialValues={{ batch_no: batchNo }}>
        <Form.Item
          name="batch_no"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>新批次号</span>}
          rules={[
            { required: true, message: '请输入批次号' },
            { max: 50, message: '批次号最长 50 个字符' },
          ]}
        >
          <Input placeholder="输入新批次号" maxLength={50} style={{ borderRadius: 6 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
