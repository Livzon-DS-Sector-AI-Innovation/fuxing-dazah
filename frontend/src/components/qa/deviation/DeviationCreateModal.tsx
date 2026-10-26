'use client'

import { useState } from 'react'
import { App, Form, Modal } from 'antd'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { createDeviation } from '@/actions/qa-deviation'
import {
  DeviationReportFields,
  reportFormInitialValues,
  reportFormToPayload,
  useQaDepartments,
  type ReportFormValues,
} from './DeviationReportFields'
import { actionError } from './shared'

/** QA 登记偏差：保存后自动生成 DE 编号并跳转到详情页继续调查。 */
export function DeviationCreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<ReportFormValues>()
  const departments = useQaDepartments()
  const [submitting, setSubmitting] = useState(false)

  const handleOk = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = await createDeviation(reportFormToPayload(values, departments))
      if (!result.success || !result.data) {
        message.error(actionError(result))
        return
      }
      message.success(`偏差 ${result.data.deviation_no} 已登记`)
      form.resetFields()
      onClose()
      // revalidatePath 只清 Next 缓存；React Query 的台账缓存要显式失效。
      void queryClient.invalidateQueries({ queryKey: ['qa', 'deviations'] })
      router.push(`/qa/deviation/${result.data.id}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="登记偏差"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="登记并生成编号"
      cancelText="取消"
      confirmLoading={submitting}
      width={880}
      destroyOnHidden
      styles={{ body: { maxHeight: 'calc(100vh - 240px)', overflowY: 'auto', paddingRight: 4 } }}
    >
      <Form form={form} layout="vertical" initialValues={reportFormInitialValues()} style={{ marginTop: 12 }}>
        <DeviationReportFields departments={departments} />
      </Form>
    </Modal>
  )
}
