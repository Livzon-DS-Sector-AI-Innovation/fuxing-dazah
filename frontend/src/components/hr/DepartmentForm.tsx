'use client'

import { useEffect, useRef, useState } from 'react'
import { App, Modal, Form, Input, Select, Spin } from 'antd'
import { Department, DepartmentCreateInput, DepartmentUpdateInput } from '@/types/hr'
import { createDepartment, fetchEmployeesAction, updateDepartment } from '@/actions/hr'
import { useDebouncedCallback } from '@/hooks/hr'

interface DepartmentFormProps {
  open: boolean
  department: Department | null
  onClose: () => void
  onSuccess: () => void
}

/** 在职人员远程搜索下拉：选项显示「姓名（工号 · 部门）」，选中存精准姓名 */
function useEmployeeOptions(open: boolean) {
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  const [searching, setSearching] = useState(false)
  const seqRef = useRef(0)

  const search = async (keyword: string) => {
    const seq = ++seqRef.current
    setSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== seqRef.current) return
      setOptions(d.data.map((e) => ({
        value: e.name,
        label: `${e.name}（${e.employee_number || '-'} · ${e.department || '-'}）`,
      })))
    } catch { /* 静默 */ }
    finally { if (seq === seqRef.current) setSearching(false) }
  }

  const { run: debouncedSearch } = useDebouncedCallback(search, 300)

  // 打开即预载首页候选（负责人通常在前列）
  useEffect(() => {
    if (open) void search('')
  }, [open])

  return { options, searching, onSearch: debouncedSearch }
}

export default function DepartmentForm({ open, department, onClose, onSuccess }: DepartmentFormProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const isEdit = !!department
  const staff = useEmployeeOptions(open)

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
    // 校验失败只走表单行内提示，不弹「操作失败」（校验错误对象没有 message）
    let values: Record<string, unknown>
    try {
      values = (await form.validateFields()) as Record<string, unknown>
    } catch {
      return
    }

    try {
      if (isEdit && department) {
        // 清空下拉后的 undefined 会被 JSON.stringify 丢弃，后端 exclude_unset 视为「不更新」，
        // 须显式传 null 才能真正清掉负责人/分管领导
        await updateDepartment(department.id, {
          ...values,
          department_manager_name: (values.department_manager_name as string | undefined) ?? null,
          supervising_leader_name: (values.supervising_leader_name as string | undefined) ?? null,
        } as unknown as DepartmentUpdateInput)
        message.success('部门更新成功')
      } else {
        await createDepartment(values as unknown as DepartmentCreateInput)
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

        <Form.Item
          name="department_manager_name"
          label="部门负责人"
          tooltip="转正评估第二级审批人；转正前 30 天提醒接收人（从在职员工中搜索选择，需其登录过系统或在源表有账号）"
        >
          <Select showSearch allowClear placeholder="搜索在职员工（姓名/工号）"
            filterOption={false} onSearch={staff.onSearch}
            notFoundContent={staff.searching ? <Spin size="small" /> : null}
            options={staff.options} />
        </Form.Item>

        <Form.Item
          name="supervising_leader_name"
          label="分管领导"
          tooltip="转正评估第三级审批人（从在职员工中搜索选择）"
        >
          <Select showSearch allowClear placeholder="搜索在职员工（姓名/工号）"
            filterOption={false} onSearch={staff.onSearch}
            notFoundContent={staff.searching ? <Spin size="small" /> : null}
            options={staff.options} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
