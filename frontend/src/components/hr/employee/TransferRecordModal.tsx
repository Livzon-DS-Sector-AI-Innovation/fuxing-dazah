'use client'

// 异动记录弹窗：历史时间线 + 新增异动表单（部门↔岗位联动）。
// 从 EmployeeTable 拆出，挂在表格行内「异动记录」入口。

import { useEffect, useState } from 'react'
import { App, Button, DatePicker, Form, Input, Modal, Select, Timeline } from 'antd'
import { createTransfer, fetchTransfers } from '@/actions/hr'
import { Employee, EmployeeTransfer } from '@/types/hr'
import { useHrDepartments, useHrPositions } from '@/hooks/hr'

interface TransferRecordModalProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
}

export default function TransferRecordModal({ open, employee, onClose }: TransferRecordModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [transfers, setTransfers] = useState<EmployeeTransfer[]>([])
  const watchedFromDept = Form.useWatch('from_department', form)
  const watchedToDept = Form.useWatch('to_department', form)
  const { departments } = useHrDepartments({ pageSize: 200 })
  const { positionsByDept } = useHrPositions()

  const deptOptions = departments.map((d) => ({ label: d.name, value: d.name }))

  // 获取某部门下的职位列表（该部门岗位优先，其余岗位兜底可选）
  const getPositions = (dept: string | undefined) => {
    const deptPositions = (dept && positionsByDept[dept]) ? positionsByDept[dept] : []
    const all = [...deptPositions]
    Object.values(positionsByDept).forEach((arr) => arr.forEach((p) => { if (!all.includes(p)) all.push(p) }))
    return all.map((p) => ({ label: p, value: p }))
  }

  // 打开时重置表单、自动填入当前部门/岗位，并拉取该员工的异动记录
  useEffect(() => {
    if (!open || !employee) return
    form.resetFields()
    form.setFieldsValue({
      from_department: employee.department || undefined,
      from_position: employee.position || undefined,
    })
    fetchTransfers({ employee_id: employee.id, page_size: 50 })
      .then((d) => setTransfers(d.data || []))
      .catch(() => setTransfers([]))
  }, [open, employee, form])

  // 换部门后若已选岗位不在新部门编制内则清掉，避免提交非法组合
  const handleDeptChange = (deptField: string, value: string) => {
    const posField = deptField === 'from_department' ? 'from_position' : 'to_position'
    const currentPos = form.getFieldValue(posField)
    if (currentPos && positionsByDept[value] && !positionsByDept[value].includes(currentPos)) {
      form.setFieldValue(posField, undefined)
    }
  }

  const handleCreate = async () => {
    const values = await form.validateFields()
    try {
      await createTransfer({
        employee_id: employee!.id,
        transfer_type: values.transfer_type,
        from_department: values.from_department || null,
        to_department: values.to_department || null,
        from_position: values.from_position || null,
        to_position: values.to_position || null,
        effective_date: values.effective_date.format('YYYY-MM-DD'),
        reason: values.reason || null,
      })
      message.success('异动记录已添加')
      form.resetFields()
      const d = await fetchTransfers({ employee_id: employee!.id, page_size: 50 })
      setTransfers(d.data || [])
    } catch (err) { message.error(err instanceof Error ? err.message : '创建失败') }
  }

  return (
    <Modal
      title={employee ? `${employee.name} — 异动记录` : '异动记录'}
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
    >
      <div className="space-y-4">
        {transfers.length > 0 ? (
          <Timeline
            items={transfers.map((t) => ({
              color: t.transfer_type === '晋升' ? 'green' : t.transfer_type === '降职' ? 'red' : 'blue',
              children: (
                <div>
                  <div className="font-medium">
                    [{t.transfer_type}] {t.from_department || '—'} → {t.to_department || '—'}
                  </div>
                  <div className="text-gray-500 text-sm">
                    {t.from_position || '—'} → {t.to_position || '—'} · {t.effective_date}
                  </div>
                  {t.reason && <div className="text-gray-400 text-xs mt-1">原因：{t.reason}</div>}
                </div>
              ),
            }))}
          />
        ) : (
          <p className="text-gray-400 text-center py-8">暂无异动记录</p>
        )}

        <div className="border-t pt-4 mt-4">
          <h4 className="font-medium mb-3">新增异动</h4>
          <Form form={form} layout="inline" className="flex flex-wrap gap-2">
            <Form.Item name="transfer_type" label="类型" rules={[{ required: true }]}>
              <Select style={{ width: 110 }} options={[
                { label: '晋升', value: '晋升' }, { label: '转岗', value: '转岗' },
                { label: '产假复岗', value: '产假复岗' },
              ]} />
            </Form.Item>
            <Form.Item name="effective_date" label="日期" rules={[{ required: true }]}>
              <DatePicker style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="from_department" label="原部门">
              <Select showSearch allowClear placeholder="原部门" style={{ width: 120 }}
                options={deptOptions}
                onChange={(v) => handleDeptChange('from_department', v)} />
            </Form.Item>
            <Form.Item name="to_department" label="新部门">
              <Select showSearch allowClear placeholder="新部门" style={{ width: 120 }}
                options={deptOptions}
                onChange={(v) => handleDeptChange('to_department', v)} />
            </Form.Item>
            <Form.Item name="from_position" label="原岗位">
              <Select showSearch allowClear placeholder="原岗位" style={{ width: 120 }}
                options={getPositions(watchedFromDept)} />
            </Form.Item>
            <Form.Item name="to_position" label="新岗位">
              <Select showSearch allowClear placeholder="新岗位" style={{ width: 120 }}
                options={getPositions(watchedToDept)} />
            </Form.Item>
            <Form.Item name="reason" label="原因"><Input style={{ width: 120 }} /></Form.Item>
            <Form.Item><Button type="primary" onClick={handleCreate}>添加</Button></Form.Item>
          </Form>
        </div>
      </div>
    </Modal>
  )
}
