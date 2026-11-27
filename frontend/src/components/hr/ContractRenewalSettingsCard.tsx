'use client'

// 劳动合同配置（系统配置 →「劳动合同」页签）。部门审批默认在系统内完成，飞书原生审批为可选增强：
// 总开关 / 公告期提前天数 / 到期预警推送部门负责人 / 飞书审批定义编码 / HR 抄送 /
// 联系人与需携带材料 / 合同归档缺失周提醒。
// 配置存 hr.system_settings（hr_contract.*），后端定时任务与审批发起前读取；
// 审批定义为空时部门审批自动降级为站内台账勾选（无需定义即可上线）。
// 系统只部署在公司内网，员工在手机上打不开本系统的链接：没有线上签字，员工到人事办公室领取合同即签收。

import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch } from 'antd'
import { getSystemSettings, updateSystemSettings } from '@/actions/hr'

interface ContractSettingsFormValues {
  renewal_pipeline_enabled: boolean
  announcement_days_ahead: number | null
  dept_head_notice_enabled: boolean
  renewal_approval_code: string
  hr_copy_open_ids: string
  contact_info: string
  contact_name: string
  required_materials: string
  archive_reminder_enabled: boolean
  archive_reminder_open_ids: string
}

const KEYS = {
  enabled: 'hr_contract.renewal_pipeline_enabled',
  days: 'hr_contract.announcement_days_ahead',
  deptHeadNotice: 'hr_contract.dept_head_notice_enabled',
  approvalCode: 'hr_contract.renewal_approval_code',
  hrCopy: 'hr_contract.hr_copy_open_ids',
  contact: 'hr_contract.contact_info',
  contactName: 'hr_contract.contact_name',
  requiredMaterials: 'hr_contract.required_materials',
  archiveEnabled: 'hr_contract.archive_reminder_enabled',
  archiveReceivers: 'hr_contract.archive_reminder_open_ids',
}

export default function ContractRenewalSettingsCard() {
  const { message } = App.useApp()
  const [form] = Form.useForm<ContractSettingsFormValues>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [approvalCode, setApprovalCode] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getSystemSettings()
        if (cancelled) return
        const kv = (res.data || {}) as Record<string, unknown>
        const str = (k: string) => (typeof kv[k] === 'string' ? (kv[k] as string) : '')
        const days = parseInt(str(KEYS.days), 10)
        form.setFieldsValue({
          renewal_pipeline_enabled: str(KEYS.enabled) !== 'false',
          announcement_days_ahead: Number.isFinite(days) && days > 0 ? days : 50,
          dept_head_notice_enabled: str(KEYS.deptHeadNotice) !== 'false',
          renewal_approval_code: str(KEYS.approvalCode),
          hr_copy_open_ids: str(KEYS.hrCopy),
          contact_info: str(KEYS.contact),
          contact_name: str(KEYS.contactName),
          required_materials: str(KEYS.requiredMaterials),
          archive_reminder_enabled: str(KEYS.archiveEnabled) !== 'false',
          archive_reminder_open_ids: str(KEYS.archiveReceivers),
        })
        setApprovalCode(str(KEYS.approvalCode))
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载配置失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (values: ContractSettingsFormValues) => {
    setSaving(true)
    try {
      await updateSystemSettings({
        [KEYS.enabled]: String(values.renewal_pipeline_enabled),
        [KEYS.days]: String(values.announcement_days_ahead ?? 50),
        [KEYS.deptHeadNotice]: String(values.dept_head_notice_enabled),
        [KEYS.approvalCode]: values.renewal_approval_code?.trim() ?? '',
        [KEYS.hrCopy]: values.hr_copy_open_ids?.trim() ?? '',
        [KEYS.contact]: values.contact_info?.trim() ?? '',
        [KEYS.contactName]: values.contact_name?.trim() ?? '',
        [KEYS.requiredMaterials]: values.required_materials?.trim() ?? '',
        [KEYS.archiveEnabled]: String(values.archive_reminder_enabled),
        [KEYS.archiveReceivers]: values.archive_reminder_open_ids?.trim() ?? '',
      })
      setApprovalCode(values.renewal_approval_code?.trim() ?? '')
      message.success('已保存')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="劳动合同续签流程" loading={loading} className="max-w-3xl">
      <div className="space-y-4">
        {!approvalCode ? (
          <Alert
            type="success"
            showIcon
            title="部门审批当前为系统内审批（默认方式）：合同进入公告期时系统给部门负责人发飞书卡片提醒，负责人在「劳动合同」里登记「同意续签 / 不同意续签」，系统记录登记人与时间。续签之前必须先有部门的「同意续签」意见。"
          />
        ) : (
          <Alert
            type="info"
            showIcon
            title="已配置飞书审批：公告期将自动发起飞书原生审批，部门负责人在飞书中完成审批，结果自动回写台账（负责人收到的是审批待办，不再另发提醒卡片）。"
          />
        )}
        <div className="text-[13px] text-[var(--color-slate)]">
          部门负责人只需要「部门续签审批」这一个权限（在权限管理里配给对应角色，并限定其部门范围），就能登记意见而看不到 HR 的其它操作。
        </div>

        <Form<ContractSettingsFormValues> form={form} layout="vertical" onFinish={(v) => void save(v)}>
          <Form.Item name="renewal_pipeline_enabled" label="续签流程总开关" valuePropName="checked">
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>

          <Form.Item
            name="announcement_days_ahead"
            label="公告期提前天数"
            extra="到期前 N 天进入公告期：通知部门负责人审批（需求默认 50 天）"
          >
            <InputNumber min={1} max={365} style={{ width: 160 }} />
          </Form.Item>

          <Form.Item
            name="dept_head_notice_enabled"
            label="到期预警推送部门负责人"
            valuePropName="checked"
            extra="合同进入公告期时给部门负责人发飞书卡片，提醒其到合同台账审批。负责人取「部门管理」里的部门负责人，没有则取员工档案的直属上级；都填了才会通知到，通知不到的在 HR 抄送的摘要里列出。本地联调请关闭，避免给真人发卡片"
          >
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>

          <Form.Item
            name="renewal_approval_code"
            label="飞书审批定义编码（可选增强，留空即用系统内审批）"
            extra="留空 = 部门审批在系统台账内完成；填写定义编码后公告期自动发起飞书原生审批（定义需在飞书审批后台创建：流程节点设「发起人自选审批人」，表单控件名：姓名、工号、部门、岗位、原合同到期日、本次签订类型、合同期限、合同起始日期、备注）"
          >
            <Input maxLength={64} placeholder="如 7C468A54-8745-2245-9675-08B7C63E7A85" allowClear />
          </Form.Item>

          <Form.Item
            name="hr_copy_open_ids"
            label="HR 抄送（姓名或 open_id，逗号分隔）"
            extra="公告期扫描摘要（含负责人未通知到的合同）、到期未续签清单发送给这些接收人"
          >
            <Input maxLength={500} placeholder="如：张三, ou_xxx" allowClear />
          </Form.Item>

          <Space size="large" wrap align="start">
            <Form.Item name="contact_info" label="联系部门" extra="员工通知里找哪个部门办理（默认「人力资源部」）">
              <Input maxLength={64} placeholder="人力资源部" allowClear />
            </Form.Item>
            <Form.Item name="contact_name" label="联系人姓名" extra="续签、领取通知里写找谁，如「王琳」；留空只写部门">
              <Input maxLength={64} placeholder="王琳" allowClear />
            </Form.Item>
          </Space>
          <Form.Item
            name="required_materials"
            label="续签需携带材料"
            extra="写进续签通知（如：身份证原件）；留空通知里不提材料"
          >
            <Input.TextArea rows={2} maxLength={200} placeholder="身份证原件" allowClear />
          </Form.Item>

          <Form.Item
            name="archive_reminder_enabled"
            label="合同归档缺失周提醒"
            valuePropName="checked"
            extra="每周一汇总未归档合同扫描件（在职 + 离职，按部门）发给 HR"
          >
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>

          <Form.Item
            name="archive_reminder_open_ids"
            label="归档提醒接收人（姓名或 open_id，逗号分隔）"
            extra="留空则沿用上面的「HR 抄送」；两处都为空时不发送"
          >
            <Input maxLength={500} placeholder="留空沿用 HR 抄送" allowClear />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={saving}>
            保存配置
          </Button>
        </Form>
      </div>
    </Card>
  )
}
