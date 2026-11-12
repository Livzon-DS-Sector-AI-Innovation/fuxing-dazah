'use client'

import { Modal, Descriptions } from 'antd'
import type { Employee } from '@/types/hr'

interface Props {
  employee: Employee | null
  open: boolean
  onClose: () => void
}

function val(v: unknown): string {
  if (v == null || v === '') return '-'
  if (Array.isArray(v)) return v.join('、') || '-'
  return String(v)
}

export default function EmployeeInfoModal({ employee, open, onClose }: Props) {
  if (!employee) return null

  // 分组与源数据表（飞书「员工信息表」）字段保持一致；「状态」为系统派生，
  // 源表没有的字段归入「系统附加」（同步模式下为空，仅手动维护的员工有值）。
  const birthText = employee.birth_year
    ? `${employee.birth_year}-${String(employee.birth_month ?? 1).padStart(2, '0')}-${String(employee.birth_day ?? 1).padStart(2, '0')}`
    : null
  const sections: [string, [string, unknown][]][] = [
    ['基本信息', [
      ['工号', employee.employee_number], ['姓名', employee.name],
      ['部门', employee.department], ['岗位', employee.position],
      ['职务', employee.duty], ['职能分类', employee.job_category],
      ['职级', employee.level], ['岗位职级', employee.report_grade],
      ['员工性质', employee.status_category], ['状态', employee.status],
      ['域账号', employee.domain_account], ['人力资源分析', employee.hr_analysis],
    ]],
    ['个人信息', [
      ['性别', employee.gender], ['出生日期', birthText],
      ['年龄', employee.computed_age], ['民族', employee.ethnicity],
      ['籍贯', employee.native_place],
      ['婚姻状况', employee.marital_status], ['户口类型', employee.household_type],
      ['身份证号', employee.id_card], ['身份证有效期', employee.id_card_expiry],
    ]],
    ['联系信息', [
      ['联系电话', employee.phone], ['居住地址', employee.current_address],
      ['紧急联系人-姓名', employee.emergency_contact_name],
      ['紧急联系人-联系电话', employee.emergency_contact_phone],
      ['紧急联系人-关系', employee.emergency_contact_relation],
    ]],
    ['教育信息', [
      ['学历', employee.education], ['学位类型', employee.degree_type],
      ['学习形式', employee.classification], ['毕业院校', employee.school],
      ['专业', employee.major], ['毕业时间', employee.graduation_date],
      ['毕业证书', employee.graduation_certificate], ['证书', employee.certificates],
    ]],
    ['工作与合同', [
      ['参加工作时间', employee.work_start_date], ['入职日期', employee.hire_date],
      ['离职日期', employee.departure_date], ['离职原因', employee.departure_reason],
      ['司龄', employee.computed_tenure ?? employee.company_tenure],
      ['任命与岗位调动', employee.transfer_history],
      ['合同开始日期', employee.contract_start_date],
      ['合同结束日期', employee.contract_end_date],
    ]],
  ]

  return (
    <Modal title={`${employee.name} · 详细信息`} open={open} onCancel={onClose} footer={null} width={800}>
      <div className="max-h-[70vh] overflow-y-auto pr-2">
        {sections.map(([title, rows]) => (
          <div key={title} className="mb-4">
            <h4 className="text-sm font-semibold text-gray-500 mb-2">{title}</h4>
            <Descriptions size="small" column={2} bordered>
              {rows.map(([label, value]) => (
                <Descriptions.Item key={label} label={label}>{val(value)}</Descriptions.Item>
              ))}
            </Descriptions>
          </div>
        ))}
      </div>
    </Modal>
  )
}
