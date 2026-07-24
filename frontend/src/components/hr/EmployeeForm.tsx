'use client'

import { useEffect, useState } from 'react'
import { App, Modal, Form, Input, Select, DatePicker, Tabs, Button, Space, Divider } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee, EmployeeCreateInput, EmployeeUpdateInput, Department } from '@/types/hr'
import { createEmployee, updateEmployee } from '@/actions/hr'
import { fetchDepartments, fetchPositions, API_BASE } from '@/lib/hr'

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
      fetchDepartments({ page_size: 100 })
        .then((res) => setDepartments(res.data))
        .catch(() => setDepartments([]))

      fetchPositions()
        .then(setPositions)
        .catch(() => setPositions([]))

      if (employee) {
        const dateFields = [
          'hire_date', 'work_start_date', 'factory_entry_date', 'livo_entry_date',
          'graduation_date', 'contract_start_date', 'contract_end_date',
          'contract_start_2', 'contract_end_2', 'contract_start_3', 'contract_end_3',
          'contract_start_4', 'contract_end_4',
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
        'hire_date', 'work_start_date', 'factory_entry_date', 'livo_entry_date',
        'graduation_date', 'contract_start_date', 'contract_end_date',
        'contract_start_2', 'contract_end_2', 'contract_start_3', 'contract_end_3',
        'contract_start_4', 'contract_end_4',
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

  const commonInput = (name: string, label: string, required?: boolean, rest?: any) => (
    <Form.Item name={name} label={label} rules={required ? [{ required: true, message: `请输入${label}` }] : undefined} {...rest}>
      <Input placeholder={`请输入${label}`} autoComplete="off" />
    </Form.Item>
  )

  const commonSelect = (name: string, label: string, options: { value: string; label: string }[], required?: boolean, showSearch?: boolean) => (
    <Form.Item name={name} label={label} rules={required ? [{ required: true, message: `请选择${label}` }] : undefined}>
      <Select placeholder={`请选择${label}`} allowClear showSearch={showSearch} options={options}
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
              {commonInput('employee_number', '工号', true)}
              {commonInput('name', '姓名', true)}
              {commonInput('domain_account', '域账号')}
              {commonSelect('department', '体现部门', departmentOptions, true)}
              {commonInput('team', '班组')}
              <Form.Item name="position" label="体现岗位" rules={[{ required: true, message: '请选择岗位' }]}>
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
              {commonInput('concurrent_departments', '兼任部门')}
              {commonInput('variety', '兼任品种')}
              {commonSelect('job_category', '职类', [
                { value: '管理', label: '管理' }, { value: '技术', label: '技术' },
                { value: '操作', label: '操作' }, { value: '职能', label: '职能' },
              ])}
              {commonSelect('level', '职级', [
                ...Array.from({length:12}, (_,i) => ({ value: `S${i+1}`, label: `S${i+1}` })),
                ...Array.from({length:8}, (_,i) => ({ value: `M${i+1}`, label: `M${i+1}` })),
              ])}
              {commonSelect('gender', '性别', [
                { value: '男', label: '男' }, { value: '女', label: '女' },
              ])}
              {commonSelect('status', '状态', [
                { value: '在职', label: '在职' }, { value: '试用期', label: '试用期' },
                { value: '离职', label: '离职' }, { value: '待审批', label: '待审批' },
                { value: '产假复岗', label: '产假复岗' },
              ], true)}
              {dateItem('hire_date', '入职日期', true)}
            </div>
          )},
          { key: 'personal', label: '个人信息', children: (
            <div className="grid grid-cols-3 gap-4">
              {commonInput('native_place', '籍贯')}
              {commonSelect('political_status', '政治面貌', [
                { value: '中共党员', label: '中共党员' }, { value: '预备党员', label: '预备党员' },
                { value: '共青团员', label: '共青团员' }, { value: '群众', label: '群众' },
                { value: '民主党派', label: '民主党派' },
              ])}
              {commonSelect('marital_status', '婚姻状况', [
                { value: '未婚', label: '未婚' }, { value: '已婚', label: '已婚' },
                { value: '离异', label: '离异' }, { value: '丧偶', label: '丧偶' },
              ])}
              {commonSelect('household_type', '户籍类型', [
                { value: '城镇', label: '城镇' }, { value: '农村', label: '农村' },
              ])}
              {commonSelect('status_category', '统计类别', [
                { value: '职员', label: '职员' }, { value: '工人', label: '工人' },
                { value: '劳务派遣', label: '劳务派遣' },
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
              {commonInput('id_card', '身份证号')}
              {commonInput('id_card_expiry', '身份证到期日')}
            </div>
          )},
          { key: 'contact', label: '联系信息', children: (
            <div className="grid grid-cols-2 gap-4">
              {commonInput('phone', '手机')}
              {commonInput('email', '邮箱')}
              {commonInput('id_card_address', '身份证地址')}
              {commonInput('current_address', '现住址')}
              {commonInput('emergency_contact_name', '紧急联系人')}
              {commonInput('emergency_contact_phone', '紧急联系人电话')}
              {commonInput('emergency_contact_relation', '紧急联系人关系')}
            </div>
          )},
          { key: 'edu', label: '学历职业', children: (
            <div className="grid grid-cols-3 gap-4">
              {commonSelect('education', '学历', [
                { value: '博士', label: '博士' }, { value: '硕士', label: '硕士' },
                { value: '本科', label: '本科' }, { value: '大专', label: '大专' },
                { value: '高中', label: '高中' }, { value: '其他', label: '其他' },
              ])}
              {commonSelect('classification', '分类', [
                { value: '全日制', label: '全日制' }, { value: '非全日制', label: '非全日制' },
              ])}
              {commonInput('school', '毕业学校')}
              {commonInput('major', '专业')}
              {dateItem('graduation_date', '毕业时间')}
              {commonSelect('qualification_type', '职称类型', [
                { value: '初级', label: '初级' }, { value: '中级', label: '中级' },
                { value: '副高级', label: '副高级' }, { value: '正高级', label: '正高级' },
              ])}
              <Form.Item name="qualifications" label="职称/职业资格">
                <Select mode="multiple" placeholder="请选择" allowClear options={[
                  { value: '高级工程师', label: '高级工程师' },
                  { value: '中级工程师', label: '中级工程师' },
                  { value: '助理工程师', label: '助理工程师' },
                  { value: '技师', label: '技师' },
                  { value: '高级技师', label: '高级技师' },
                  { value: '注册会计师', label: '注册会计师' },
                ]} />
              </Form.Item>
              {dateItem('work_start_date', '参加工作时间')}
              {dateItem('factory_entry_date', '进厂时间')}
              {dateItem('livo_entry_date', '入丽珠时间')}
            </div>
          )},
          { key: 'contract', label: '合同信息', children: (
            <div className="grid grid-cols-2 gap-4">
              {commonSelect('contract_type', '合同期限', [
                { value: '无固定期限', label: '无固定期限' },
                { value: '固定期限', label: '固定期限' },
                { value: '3年', label: '3年' },
                { value: '5年', label: '5年' },
              ])}
              {dateItem('contract_start_date', '第一次合同起点')}
              {dateItem('contract_end_date', '第一次合同终止')}
              {dateItem('contract_start_2', '第二次合同起点')}
              {dateItem('contract_end_2', '第二次合同终止')}
              {dateItem('contract_start_3', '第三次合同起点')}
              {dateItem('contract_end_3', '第三次合同终止')}
              {dateItem('contract_start_4', '第四次合同起点')}
              {dateItem('contract_end_4', '第四次合同终止')}
            </div>
          )},
          { key: 'other', label: '其他', children: (
            <div className="grid grid-cols-2 gap-4">
              {commonInput('bank_account', '银行卡号')}
              {commonInput('training_id', '培训档案编号')}
              {commonInput('transfer_history', '异动记录')}
              <Form.Item name="remarks" label="备注">
                <Select mode="tags" placeholder="输入备注" allowClear />
              </Form.Item>
            </div>
          )},
        ]} />
      </Form>

      <Modal title="新建职位" open={newPosModalOpen} onCancel={() => setNewPosModalOpen(false)}
        onOk={async () => {
          if (!newPosName.trim()) { message.warning('请输入职位名称'); return }
          try {
            const res = await fetch(`${API_BASE}/api/v1/hr/positions`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ department: newPosDept, name: newPosName.trim() }),
            })
            if (res.ok) {
              message.success('职位创建成功')
              setNewPosModalOpen(false)
              const data = await fetchPositions()
              setPositions(data)
              form.setFieldValue('position', newPosName.trim())
            } else {
              const d = await res.json(); message.error(d.message || '创建失败')
            }
          } catch { message.error('创建失败') }
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
