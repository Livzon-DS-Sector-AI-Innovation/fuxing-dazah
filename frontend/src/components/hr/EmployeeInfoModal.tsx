'use client'

import { Modal, Descriptions } from 'antd'
import type { Employee } from '@/types/hr'

interface Props {
  employee: Employee | null
  open: boolean
  onClose: () => void
}

function items(arr: [string, unknown][]): [string, unknown][] {
  return arr.filter(([, v]) => v != null && v !== '')
}

export default function EmployeeInfoModal({ employee, open, onClose }: Props) {
  if (!employee) return null
  const e = employee as unknown as Record<string, unknown>

  const sections: [string, [string, unknown][]][] = [
    ['基本信息', items([
      ['域账号', e.domain_account], ['性别', e.gender], ['籍贯', e.native_place],
      ['政治面貌', e.political_status], ['婚姻状况', e.marital_status],
      ['户籍类型', e.household_type], ['身份证号', e.id_card],
      ['身份证到期', e.id_card_expiry], ['身份证地址', e.id_card_address],
      ['现住址', e.current_address], ['手机', e.phone], ['邮箱', e.email],
    ])],
    ['学历信息', items([
      ['学历', e.education], ['全日制/非全日制', e.classification],
      ['毕业院校', e.school], ['专业', e.major], ['毕业时间', e.graduation_date],
    ])],
    ['工作履历与职级', items([
      ['参加工作时间', e.work_start_date], ['进厂时间', e.factory_entry_date],
      ['入丽珠时间', e.livo_entry_date], ['离职时间', e.departure_date],
      ['职类', e.job_category], ['级别', e.level], ['职务', e.duty],
      ['报表用职级', e.report_grade], ['职称/职业资格', Array.isArray(e.qualifications) ? (e.qualifications as string[]).join('、') : e.qualifications],
      ['职称类型', e.qualification_type],
    ])],
    ['管理信息', items([
      ['部门管理者', e.dept_manager], ['额外管理者', e.additional_manager],
      ['部门负责人/培训师', e.dept_head_trainer], ['兼任品种', e.concurrent_variety],
    ])],
    ['合同信息', items([
      ['合同期限', e.contract_type], ['合同1起', e.contract_start_date], ['合同1止', e.contract_end_date],
      ['合同2起', e.contract_start_2], ['合同2止', e.contract_end_2],
      ['合同3起', e.contract_start_3], ['合同3止', e.contract_end_3],
      ['合同4起', e.contract_start_4], ['合同4止', e.contract_end_4],
    ])],
    ['紧急联系人', items([
      ['紧急联系人', e.emergency_contact_name], ['紧急联系电话', e.emergency_contact_phone],
      ['与本人关系', e.emergency_contact_relation],
    ])],
    ['培训记录', items([
      ['入职安全培训日期', e.safety_training_date], ['安全培训成绩', e.safety_training_score],
      ['企业文化培训日期', e.culture_training_date], ['GMP培训日期', e.gmp_training_date],
    ])],
    ['其他信息', items([
      ['银行账号', e.bank_account], ['员工性质', e.status_category], ['证书', e.certificates],
      ['工龄(年)', e.work_years], ['厂龄', e.factory_tenure], ['司龄', e.company_tenure],
      ['出生年', e.birth_year], ['出生月', e.birth_month], ['出生日', e.birth_day],
    ])],
  ]

  return (
    <Modal title={`${e.name} · 详细信息`} open={open} onCancel={onClose} footer={null} width={800}>
      <div className="max-h-[70vh] overflow-y-auto pr-2">
        {sections.map(([title, rows]) =>
          rows.length > 0 ? (
            <div key={title} className="mb-4">
              <h4 className="text-sm font-semibold text-gray-500 mb-2">{title}</h4>
              <Descriptions size="small" column={2} bordered>
                {rows.map(([label, value]) => (
                  <Descriptions.Item key={label as string} label={label as string}>
                    {String(value ?? '-')}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </div>
          ) : null
        )}
      </div>
    </Modal>
  )
}
