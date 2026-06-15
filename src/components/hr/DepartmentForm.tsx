'use client'

import { useEffect } from 'react'
import { App, Modal, Form, Input } from 'antd'
import { Department, DepartmentCreateInput, DepartmentUpdateInput } from '@/types/hr'
import { createDepartment, updateDepartment } from '@/actions/hr'

interface DepartmentFormProps {
  open: boolean
  department: Department | null
  onClose: () => void
  onSuccess: () => void
}

export default function DepartmentForm({ open, department, onClose, onSuccess }: DepartmentFormProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const isEdit = !!department

  useEffect(() => {
    if (open) {
      if (department) {
        form.setFieldsValue(department)
      } else {
        form.resetFields()
        form.setFieldsValue({ sort_order: 0 })
      }
    }
  }, [open, department, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()

      if (isEdit && department) {
        await updateDepartment(department.id, values as DepartmentUpdateInput)
        message.success('部门更新成功')
      } else {
        await createDepartment(values as DepartmentCreateInput)
        message.success('部门创建成功')
      }

      form.resetFields()
      onSuccess()
      onClose()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  return (
    <Modal
      title={isEdit ? '编辑部门' : '新增部门'}
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      width={480}
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="name"
          label="部门名称"
          rules={[{ required: true, message: '请输入部门名称' }]}
        >
          <Input placeholder="请输入部门名称" />
        </Form.Item>

        <Form.Item
          name="code"
          label="部门编码"
          rules={[{ required: true, message: '请输入部门编码' }]}
        >
          <Input placeholder="请输入部门编码" />
        </Form.Item>

        <Form.Item
          name="description"
          label="部门描述"
        >
          <Input.TextArea rows={2} placeholder="请输入部门描述" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
