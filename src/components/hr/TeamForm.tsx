'use client'

import { useEffect } from 'react'
import { App, Modal, Form, Input } from 'antd'
import { Team, TeamCreateInput, TeamUpdateInput } from '@/types/hr'
import { createTeam, updateTeam } from '@/actions/hr'

interface TeamFormProps {
  open: boolean
  team: Team | null
  departmentId: string
  onClose: () => void
  onSuccess: () => void
}

export default function TeamForm({ open, team, departmentId, onClose, onSuccess }: TeamFormProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const isEdit = !!team

  useEffect(() => {
    if (open) {
      if (team) {
        form.setFieldsValue({
          name: team.name,
          code: team.code,
          description: team.description })
      } else {
        form.resetFields()
      }
    }
  }, [open, team, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()

      if (isEdit && team) {
        await updateTeam(team.id, values as TeamUpdateInput)
        message.success('班组更新成功')
      } else {
        await createTeam({ ...values, department_id: departmentId } as TeamCreateInput)
        message.success('班组创建成功')
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
      title={isEdit ? '编辑班组' : '新增班组'}
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
          label="班组名称"
          rules={[{ required: true, message: '请输入班组名称' }]}
        >
          <Input placeholder="请输入班组名称" />
        </Form.Item>

        <Form.Item
          name="code"
          label="班组编码"
        >
          <Input placeholder="请输入班组编码" />
        </Form.Item>

        <Form.Item
          name="description"
          label="班组描述"
        >
          <Input.TextArea rows={2} placeholder="请输入班组描述" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
