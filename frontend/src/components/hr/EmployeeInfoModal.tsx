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

  const sections: [string, [string, unknown][]][] = [
    ['基本信息', [
      ['域账号', employee.domain_account], ['性别', employee.gender], ['籍贯', employee.native_place],
      ['政治面貌', employee.political_status], ['婚姻状况', employee.marital_status],
      ['户籍类型', employee.household_type], ['身份证号', employee.id_card],
      ['身份证到期', employee.id_card_expiry], ['身份证地址', employee.id_card_address],
      ['现住址', employee.current_address], ['手机', employee.phone], ['邮箱', employee.email],
    ]],
    ['学历信息', [
      ['学历', employee.education], ['全日制/非全日制', employee.classification as unknown],
      ['毕业院校', employee.school], ['专业', employee.major], ['毕业时间', employee.graduation_date],
    ]],
    ['工作履历与职级', [
      ['参加工作时间', employee.work_start_date], ['进厂时间', employee.factory_entry_date],
      ['入丽珠时间', employee.livo_entry_date], ['离职时间', employee.departure_date as unknown],
      ['职类', employee.job_category], ['级别', employee.level], ['职务', employee.duty as unknown],
      ['报表用职级', employee.report_grade as unknown],
      ['职称/职业资格', employee.qualifications],
      ['职称类型', employee.qualification_type],
    ]],
    ['管理信息', [
      ['部门管理者', employee.dept_manager as unknown], ['额外管理者', employee.additional_manager as unknown],
      ['部门负责人/培训师', employee.dept_head_trainer as unknown], ['兼任品种', employee.concurrent_variety as unknown],
    ]],
    ['合同信息', [
      ['合同期限', employee.contract_type], ['合同1起', employee.contract_start_date], ['合同1止', employee.contract_end_date],
      ['合同2起', employee.contract_start_2 as unknown], ['合同2止', employee.contract_end_2 as unknown],
      ['合同3起', employee.contract_start_3 as unknown], ['合同3止', employee.contract_end_3 as unknown],
      ['合同4起', employee.contract_start_4 as unknown], ['合同4止', employee.contract_end_4 as unknown],
    ]],
    ['紧急联系人', [
      ['紧急联系人', employee.emergency_contact_name], ['紧急联系电话', employee.emergency_contact_phone],
      ['与本人关系', employee.emergency_contact_relation],
    ]],
    ['培训记录', [
      ['入职安全培训日期', employee.safety_training_date as unknown], ['安全培训成绩', employee.safety_training_score as unknown],
      ['企业文化培训日期', employee.culture_training_date as unknown], ['GMP培训日期', employee.gmp_training_date as unknown],
    ]],
    ['其他信息', [
      ['银行账号', employee.bank_account], ['员工性质', employee.status_category],
      ['证书', employee.certificates as unknown],
      ['工龄(年)', employee.work_years], ['厂龄', employee.factory_tenure], ['司龄', employee.company_tenure],
      ['出生年', employee.birth_year], ['出生月', employee.birth_month], ['出生日', employee.birth_day],
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
