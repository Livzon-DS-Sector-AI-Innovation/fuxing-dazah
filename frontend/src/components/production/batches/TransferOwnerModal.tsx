'use client'

import { useState } from 'react'
import { Alert, App, Form, Modal } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { transferBatchOwner } from '@/actions/production'
import { UserSelect } from '@/components/shared'

interface Props {
  batchId: string
  batchNo: string
  currentOwnerName: string | null
  onClose: () => void
}

export function TransferOwnerModal({
  batchId,
  batchNo,
  currentOwnerName,
  onClose,
}: Props) {
  const [form] = Form.useForm()
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)

  const doTransfer = async (newOwnerId: string | null) => {
    setSubmitting(true)
    try {
      const result = await transferBatchOwner(batchId, newOwnerId)
      if (result.success) {
        message.success(newOwnerId ? '负责人已转移' : '负责人已清空')
        // 归属变化影响：详情、列表负责人列、工作台「我的批次」
        queryClient.invalidateQueries({ queryKey: ['production-batch-detail', batchId] })
        queryClient.invalidateQueries({ queryKey: ['production-batches'] })
        queryClient.invalidateQueries({ queryKey: ['production-workbench'] })
        onClose()
      } else {
        message.error(result.error ?? '转移失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const newOwnerId = (values.owner_user_id as string | undefined) ?? null
    if (newOwnerId === null && !currentOwnerName) {
      message.info('当前批次已是无主状态')
      return
    }
    // 未选择新负责人时提交 = 清空负责人，属破坏性变更，需二次确认防误点
    if (newOwnerId === null && currentOwnerName) {
      modal.confirm({
        title: '未选择新负责人，确认清空负责人？',
        content: '清空后批次恢复无主共享状态：工段内人员均可操作，首次开工会被认领。',
        okText: '清空负责人',
        okButtonProps: { danger: true },
        onOk: () => doTransfer(null),
      })
      return
    }
    await doTransfer(newOwnerId)
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>
          转移批次负责人 · {batchNo}
        </span>
      }
      open
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
      width={520}
      okText="确认转移"
      cancelText="取消"
      confirmLoading={submitting}
      styles={{ body: { padding: '16px 24px' } }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title={`当前负责人：${currentOwnerName ?? '无（共享状态）'}。转移后该批次的归属操作权、工作台「我的批次」及提醒接收人都将跟随新负责人，已开始工序的单次执行负责人不受影响。`}
      />
      <Form form={form} layout="vertical">
        <Form.Item
          name="owner_user_id"
          label={<span style={{ fontSize: 13, fontWeight: 500, color: '#37352f' }}>新负责人</span>}
          extra="清空则恢复无主共享状态（工段内可操作，首次开工会被认领）"
        >
          <UserSelect
            placeholder="搜索并选择新负责人"
            style={{ width: '100%' }}
            allowClear
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
