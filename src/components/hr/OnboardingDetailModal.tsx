'use client'

import { Modal, Descriptions } from 'antd'
import { OnboardingRecord } from '@/types/hr'

interface OnboardingDetailModalProps {
  open: boolean
  record: OnboardingRecord | null
  onClose: () => void
}

export default function OnboardingDetailModal({
  open,
  record,
  onClose,
}: OnboardingDetailModalProps) {
  if (!record) return null

  const sections = [
    {
      key: 'basic',
      label: '基本信息',
      items: [
        { label: '编号', value: record.seq_number },
        { label: '工号', value: record.employee_number },
        { label: '姓名', value: record.name },
        { label: '域账号', value: record.domain_account },
        { label: '部门', value: record.department },
        { label: '班组', value: record.team },
        { label: '岗位', value: record.position },
        { label: '职类', value: record.job_category },
        { label: '统计类别', value: record.status_category },
        { label: '是否在职', value: record.is_employed },
      ],
    },
    {
      key: 'dates',
      label: '日期信息',
      items: [
        { label: '入职时间', value: record.hire_date },
        { label: '进厂时间', value: record.factory_entry_date },
        { label: '入丽珠时间', value: record.livo_entry_date },
        { label: '参加工作时间', value: record.work_start_date },
        { label: '毕业时间', value: record.graduation_date },
        {
          label: '出生月日',
          value:
            record.birth_month && record.birth_day
              ? `${record.birth_month}月${record.birth_day}日`
              : undefined,
        },
        { label: '年龄', value: record.age },
        { label: '工作年限', value: record.work_years },
        { label: '厂龄', value: record.factory_tenure },
        { label: '司龄', value: record.company_tenure },
        { label: '入职月份', value: record.hire_month },
      ],
    },
    {
      key: 'education',
      label: '教育背景',
      items: [
        { label: '学历', value: record.education },
        { label: '毕业学校', value: record.school },
        { label: '专业', value: record.major },
        { label: '分类', value: record.classification },
      ],
    },
    {
      key: 'personal',
      label: '个人信息',
      items: [
        { label: '身份证号', value: record.id_card },
        { label: '身份证到期日', value: record.id_card_expiry },
        { label: '身份证地址', value: record.id_card_address },
        { label: '现住址', value: record.current_address },
        { label: '婚姻状况', value: record.marital_status },
        { label: '户籍类型', value: record.household_type },
        { label: '政治面貌', value: record.political_status },
      ],
    },
    {
      key: 'contact',
      label: '联系方式',
      items: [
        { label: '手机', value: record.phone },
        { label: '邮箱', value: record.email },
        { label: '紧急联系人电话', value: record.emergency_contact_phone },
        { label: '紧急联系人|关系', value: record.emergency_contact_relation },
      ],
    },
    {
      key: 'contract',
      label: '合同信息',
      items: [
        { label: '合同期限', value: record.contract_type },
        { label: '第一次合同起点', value: record.contract_start_date },
        { label: '第一次合同终止', value: record.contract_end_date },
        { label: '第二次合同起点', value: record.contract_start_2 },
        { label: '第二次合同终止', value: record.contract_end_2 },
        { label: '第三次合同起点', value: record.contract_start_3 },
        { label: '第三次合同终止', value: record.contract_end_3 },
        { label: '第四次合同起点', value: record.contract_start_4 },
        { label: '第四次合同终止', value: record.contract_end_4 },
      ],
    },
    {
      key: 'other',
      label: '其他',
      items: [
        { label: '银行卡号', value: record.bank_account },
        { label: '银行卡开户地', value: record.bank_account_location },
        { label: '培训档案编号', value: record.training_id },
        { label: '异动记录', value: record.transfer_history },
        { label: '备注', value: record.remarks?.join(', ') },
        { label: '飞书同步时间', value: record.feishu_synced_at },
      ],
    },
  ]

  return (
    <Modal
      title={`入职详情 - ${record.name}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={800}
      styles={{ body: { maxHeight: '70vh', overflow: 'auto' } }}
    >
      <div className="space-y-6">
        {sections.map((section) => (
          <div key={section.key}>
            <h3 className="text-base font-medium mb-3 text-[var(--color-charcoal)]">
              {section.label}
            </h3>
            <Descriptions bordered size="small" column={2}>
              {section.items.map((item) => (
                <Descriptions.Item key={item.label} label={item.label}>
                  {item.value || '-'}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </div>
        ))}
      </div>
    </Modal>
  )
}
