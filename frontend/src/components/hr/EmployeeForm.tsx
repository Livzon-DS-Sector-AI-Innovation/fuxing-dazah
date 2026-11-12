'use client'

import { useEffect, useState } from 'react'
import { App, Modal, Form, Input, Select, DatePicker, Tabs, Button, Space, Divider } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee, EmployeeCreateInput, EmployeeUpdateInput, Department } from '@/types/hr'
import { createEmployee, updateEmployee } from '@/actions/hr'
import { fetchDepartmentsAction, fetchPositions, createPosition } from '@/actions/hr'

interface EmployeeFormProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
  onSuccess: () => void
}


export default function EmployeeForm({ open, employee, onClose, onSuccess }: EmployeeFormProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const isEdit = !!employee
  const [departments, setDepartments] = useState<Department[]>([])
  const [positions, setPositions] = useState<any[]>([])
  const [newPosModalOpen, setNewPosModalOpen] = useState(false)
  const [newPosName, setNewPosName] = useState('')
  const [newPosDept, setNewPosDept] = useState('')

  useEffect(() => {
    if (open) {
      fetchDepartmentsAction({ page_size: 100 })
        .then((res) => setDepartments(res.data))
        .catch(() => setDepartments([]))

      fetchPositions()
        .then(setPositions)
        .catch(() => setPositions([]))

      if (employee) {
        const dateFields = [
          'hire_date', 'work_start_date', 'departure_date',
          'graduation_date', 'contract_start_date', 'contract_end_date',
        ]
        const values: any = { ...employee }
        dateFields.forEach((f) => {
          const val = employee[f as keyof Employee]
          if (val && typeof val === 'string') {
            values[f] = dayjs(val)
          }
        })
        form.setFieldsValue(values)
      } else {
        form.resetFields()
        form.setFieldsValue({ status: '在职' })
      }
    }
  }, [open, employee, form])

  const selectedDept = Form.useWatch('department', form)
  const positionOptions = (selectedDept ? positions.filter((p: any) => p.department === selectedDept) : positions)
    .map((p: any) => ({ value: p.name, label: p.name }))

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const dateFields = [
        'hire_date', 'work_start_date', 'departure_date',
        'graduation_date', 'contract_start_date', 'contract_end_date',
      ]
      const payload: any = { ...values }
      dateFields.forEach((f) => {
        if (values[f]) {
          payload[f] = values[f].format('YYYY-MM-DD')
        }
      })

      if (isEdit && employee) {
        await updateEmployee(employee.id, payload as EmployeeUpdateInput)
        message.success('员工更新成功')
      } else {
        await createEmployee(payload as EmployeeCreateInput)
        message.success('员工创建成功')
      }

      form.resetFields()
      onSuccess()
      onClose()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const departmentOptions = departments.map((d) => ({ value: d.name, label: d.name }))

  const commonInput = (name: string, label: string, required?: boolean, rest?: any, disabled = false) => (
    <Form.Item name={name} label={label} rules={required ? [{ required: true, message: `请输入${label}` }] : undefined} {...rest}>
      <Input placeholder={`请输入${label}`} autoComplete="off" disabled={disabled} />
    </Form.Item>
  )

  const commonSelect = (name: string, label: string, options: { value: string; label: string }[], required?: boolean, showSearch?: boolean, disabled = false) => (
    <Form.Item name={name} label={label} rules={required ? [{ required: true, message: `请选择${label}` }] : undefined}>
      <Select placeholder={`请选择${label}`} allowClear showSearch={showSearch} disabled={disabled} options={options}
        filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
    </Form.Item>
  )

  const dateItem = (name: string, label: string, required?: boolean) => (
    <Form.Item name={name} label={label} rules={required ? [{ required: true, message: `请选择${label}` }] : undefined}>
      <DatePicker className="w-full" placeholder={`请选择${label}`} />
    </Form.Item>
  )

  return (
    <Modal
      title={isEdit ? '编辑员工' : '新增员工'}
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      width={860}
    >
      <Form form={form} layout="vertical" className="mt-4" autoComplete="off">
        <Tabs defaultActiveKey="basic" items={[
          { key: 'basic', label: '基本信息', children: (
            <div className="grid grid-cols-3 gap-4">
              {commonInput('employee_number', '工号', true, undefined, isEdit)}
              {commonInput('name', '姓名', true, undefined, isEdit)}
              {commonSelect('department', '部门', departmentOptions, true)}
              <Form.Item name="position" label="岗位" rules={[{ required: true, message: '请选择岗位' }]}>
                <Select placeholder="请选择岗位" allowClear showSearch
                  filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
                  options={positionOptions}
                  dropdownRender={(menu) => (
                    <>
                      {menu}
                      <Divider style={{ margin: '8px 0' }} />
                      <Button type="link" icon={<PlusOutlined />} style={{ width: '100%', textAlign: 'left' }}
                        onClick={async () => {
                          const dept = form.getFieldValue('department')
                          if (!dept) { message.warning('请先选择部门'); return }
                          setNewPosDept(dept)
                          setNewPosName('')
                          setNewPosModalOpen(true)
                        }}>
                        新建职位
                      </Button>
                    </>
                  )} />
              </Form.Item>
              {commonInput('duty', '职务')}
              {commonSelect('job_category', '职能分类', [
                { value: '生产', label: '生产' },
                { value: '生产辅助', label: '生产辅助' },
                { value: '职能管理', label: '职能管理' },
                { value: '研发', label: '研发' },
                { value: '后勤辅助', label: '后勤辅助' },
              ])}
              {commonSelect('level', '职级', [
                ...Array.from({length:12}, (_,i) => ({ value: `S${i+1}`, label: `S${i+1}` })),
                ...Array.from({length:8}, (_,i) => ({ value: `M${i+1}`, label: `M${i+1}` })),
              ])}
              {commonSelect('report_grade', '岗位职级', [
                { value: '职业技能岗位', label: '职业技能岗位' },
                { value: 'S10以上管理', label: 'S10以上管理' },
                { value: '技术职级', label: '技术职级' },
                { value: '主操', label: '主操' },
              ])}
              {commonSelect('status_category', '员工性质', [
                { value: '转正员工', label: '转正员工' },
                { value: '试用期', label: '试用期' },
                { value: '实习转试用', label: '实习转试用' },
                { value: '实习生', label: '实习生' },
                { value: '退休返聘', label: '退休返聘' },
              ])}
              {commonSelect('gender', '性别', [
                { value: '男', label: '男' }, { value: '女', label: '女' },
              ], undefined, undefined, isEdit)}
              {commonSelect('status', '状态', [
                { value: '在职', label: '在职' }, { value: '试用期', label: '试用期' },
                { value: '离职', label: '离职' }, { value: '待审批', label: '待审批' },
                { value: '病假', label: '病假' }, { value: '产假', label: '产假' },
                { value: '产假复岗', label: '产假复岗' },
              ], true)}
              {dateItem('hire_date', '入职日期', true)}
              {commonInput('domain_account', '域账号')}
              {commonSelect('hr_analysis', '人力资源分析', [
                { value: '生产一线', label: '生产一线' },
                { value: '技术一线', label: '技术一线' },
                { value: '研发一线', label: '研发一线' },
                { value: '职能人员', label: '职能人员' },
                { value: '生产辅助', label: '生产辅助' },
                { value: '后勤服务', label: '后勤服务' },
              ])}
            </div>
          )},
          { key: 'personal', label: '个人信息', children: (
            <div className="grid grid-cols-3 gap-4">
              {commonInput('native_place', '籍贯')}
              {commonInput('ethnicity', '民族')}
              {commonSelect('marital_status', '婚姻状况', [
                { value: '未婚', label: '未婚' }, { value: '已婚', label: '已婚' },
                { value: '离异', label: '离异' }, { value: '丧偶', label: '丧偶' },
              ])}
              {commonSelect('household_type', '户口类型', [
                { value: '城镇', label: '城镇' }, { value: '农村', label: '农村' },
              ])}
              <Form.Item name="birth_year" label="出生年份">
                <Input type="number" placeholder="如: 1990" />
              </Form.Item>
              <Form.Item name="birth_month" label="出生月份">
                <Input type="number" placeholder="如: 5" />
              </Form.Item>
              <Form.Item name="birth_day" label="出生日期">
                <Input type="number" placeholder="如: 15" />
              </Form.Item>
              {commonInput('id_card', '身份证号', undefined, undefined, isEdit)}
              {commonInput('id_card_expiry', '身份证有效期')}
            </div>
          )},
          { key: 'contact', label: '联系信息', children: (
            <div className="grid grid-cols-2 gap-4">
              {commonInput('phone', '联系电话')}
              {commonInput('current_address', '居住地址')}
              {commonInput('emergency_contact_name', '紧急联系人-姓名')}
              {commonInput('emergency_contact_phone', '紧急联系人-联系电话')}
              {commonInput('emergency_contact_relation', '紧急联系人-关系')}
            </div>
          )},
          { key: 'edu', label: '教育信息', children: (
            <div className="grid grid-cols-3 gap-4">
              {commonSelect('education', '学历', [
                { value: '博士', label: '博士' }, { value: '硕士', label: '硕士' },
                { value: '本科', label: '本科' }, { value: '大专', label: '大专' },
                { value: '中专', label: '中专' }, { value: '中专/中技', label: '中专/中技' },
                { value: '高中', label: '高中' }, { value: '初中', label: '初中' },
                { value: '其他', label: '其他' },
              ])}
              {commonInput('degree_type', '学位类型')}
              {commonSelect('classification', '学习形式', [
                { value: '全日制', label: '全日制' }, { value: '非全日制', label: '非全日制' },
              ])}
              {commonInput('school', '毕业院校')}
              {commonInput('major', '专业')}
              {dateItem('graduation_date', '毕业时间')}
              {commonInput('graduation_certificate', '毕业证书')}
              {commonInput('certificates', '证书')}
            </div>
          )},
          { key: 'work', label: '工作与合同', children: (
            <div className="grid grid-cols-2 gap-4">
              {dateItem('work_start_date', '参加工作时间')}
              {dateItem('hire_date', '入职日期', true)}
              {dateItem('departure_date', '离职日期')}
              {commonSelect('departure_reason', '离职原因', [
                { value: '个人原因', label: '个人原因' },
                { value: '实习结束', label: '实习结束' },
                { value: '退休', label: '退休' },
                { value: '退休返聘到期', label: '退休返聘到期' },
                { value: '调合成公司', label: '调合成公司' },
                { value: '其他', label: '其他' },
              ])}
              {commonInput('transfer_history', '任命与岗位调动')}
              {dateItem('contract_start_date', '合同开始日期')}
              {dateItem('contract_end_date', '合同结束日期')}
            </div>
          )},
        ]} />
      </Form>

      <Modal title="新建职位" open={newPosModalOpen} onCancel={() => setNewPosModalOpen(false)}
        onOk={async () => {
          if (!newPosName.trim()) { message.warning('请输入职位名称'); return }
          try {
            await createPosition({ department: newPosDept, name: newPosName.trim() })
            message.success('职位创建成功')
            setNewPosModalOpen(false)
            const data = await fetchPositions()
            setPositions(data)
            form.setFieldValue('position', newPosName.trim())
          } catch (err) { message.error((err as Error)?.message || '创建失败') }
        }} okText="创建">
        <div className="mt-4 space-y-3">
          <div><strong>部门：</strong>{newPosDept}</div>
          <Input placeholder="输入职位名称" value={newPosName}
            onChange={e => setNewPosName(e.target.value)} />
        </div>
      </Modal>
    </Modal>
  )
}
