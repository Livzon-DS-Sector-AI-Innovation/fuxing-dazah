'use client'

import { useState } from 'react'
import { App, Form, Input, Modal, Select } from 'antd'
import { createPosition } from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import type { PositionOption } from '@/types/hr'

interface PositionFormValues {
  department: string
  name: string
}

export interface CreatedPosition {
  id: string
  department: string
  name: string
}

interface PositionFormModalProps {
  open: boolean
  /** 打开时所处视图的部门；「全部岗位」视图下不传 */
  defaultDepartment?: string
  /** 部门下拉选项，组织架构顺序 */
  departments: string[]
  /** 现有岗位，用来拦住同部门同名 */
  positions: PositionOption[]
  onClose: () => void
  onCreated: (created: CreatedPosition) => void
}

/** 新增岗位。岗位名称是员工档案、培训各处选岗时的显示值，所以限选组织架构里的部门、不允许自由录入 */
export default function PositionFormModal({
  open,
  defaultDepartment,
  departments,
  positions,
  onClose,
  onCreated,
}: PositionFormModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<PositionFormValues>()
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  // 只在弹窗打开且确有改动时拦，放弃/保存后复位 dirty：
  // 组件关闭后仍挂着，不复位的话之后每次刷新都会被 beforeunload 的「离开站点？」拦住
  const guardClose = useUnsavedConfirm(dirty && open, () => {
    setDirty(false)
    onClose()
  })

  const submit = async () => {
    // 校验失败只走表单行内提示
    let values: PositionFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const name = values.name.trim()
    setSaving(true)
    try {
      const res = await createPosition({
        department: values.department,
        name,
      })
      message.success(`已新增岗位「${name}」`)
      setDirty(false)
      onCreated(res.data as CreatedPosition)
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '新增失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="新增岗位"
      open={open}
      okText="新增"
      cancelText="取消"
      confirmLoading={saving}
      onOk={() => { void submit() }}
      onCancel={guardClose}
      destroyOnHidden
      width={440}
    >
      <Form<PositionFormValues>
        form={form}
        layout="vertical"
        className="mt-4"
        initialValues={{ department: defaultDepartment || undefined }}
        onValuesChange={(changed) => {
          setDirty(true)
          // 同名校验要看所选的部门：换了部门就把已填的岗位名称重新校验一遍
          if ('department' in changed && form.isFieldTouched('name')) {
            form.validateFields(['name']).catch(() => { /* 错误已在字段下方提示 */ })
          }
        }}
      >
        <Form.Item
          name="department"
          label="部门"
          rules={[{ required: true, message: '请选择部门' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择部门"
            options={departments.map((d) => ({ value: d, label: d }))}
          />
        </Form.Item>

        <Form.Item
          name="name"
          label="岗位名称"
          rules={[
            { required: true, whitespace: true, message: '请输入岗位名称' },
            { max: 128, message: '岗位名称不能超过 128 个字符' },
            {
              validator: (_rule, value: string | undefined) => {
                const dept = form.getFieldValue('department') as string | undefined
                const name = value?.trim()
                if (dept && name && positions.some((p) => p.department === dept && p.name === name)) {
                  return Promise.reject(new Error(`「${dept}」下已经有岗位「${name}」了`))
                }
                return Promise.resolve()
              },
            },
          ]}
        >
          <Input maxLength={128} placeholder="如：操作工" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
