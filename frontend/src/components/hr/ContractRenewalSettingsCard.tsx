'use client'

// 劳动合同配置（系统配置 →「劳动合同」页签）。部门审批默认在系统内完成，飞书原生审批为可选增强：
// 总开关 / 公告期提前天数 / 到期预警推送部门负责人 / 飞书审批定义编码 / HR 抄送 / 签字页地址 /
// 联系人文案 / 合同归档缺失周提醒。
// 配置存 hr.system_settings（hr_contract.*），后端定时任务与审批发起前读取；
// 审批定义为空时部门审批自动降级为站内台账勾选（无需定义即可上线）。

import { useEffect, useState } from 'react'
import { App, Alert, Button, Card, Form, Input, InputNumber, Switch } from 'antd'
import { getSystemSettings, updateSystemSettings } from '@/actions/hr'

interface ContractSettingsFormValues {
  renewal_pipeline_enabled: boolean
  announcement_days_ahead: number | null
  dept_head_notice_enabled: boolean
  renewal_approval_code: string
  hr_copy_open_ids: string
  sign_page_base_url: string
  contact_info: string
  archive_reminder_enabled: boolean
  archive_reminder_open_ids: string
}

const KEYS = {
  enabled: 'hr_contract.renewal_pipeline_enabled',
  days: 'hr_contract.announcement_days_ahead',
  deptHeadNotice: 'hr_contract.dept_head_notice_enabled',
  approvalCode: 'hr_contract.renewal_approval_code',
  hrCopy: 'hr_contract.hr_copy_open_ids',
  signBase: 'hr_contract.sign_page_base_url',
  contact: 'hr_contract.contact_info',
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
          sign_page_base_url: str(KEYS.signBase),
          contact_info: str(KEYS.contact),
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
        [KEYS.signBase]: values.sign_page_base_url?.trim().replace(/\/+$/, '') ?? '',
        [KEYS.contact]: values.contact_info?.trim() ?? '',
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
            title="部门审批当前为系统内审批（默认方式）：合同进入公告期时系统给部门负责人发飞书卡片提醒，负责人在合同台账里勾选「同意续签 / 不同意续签」，系统记录审批时间。"
          />
        ) : (
          <Alert
            type="info"
            showIcon
            title="已配置飞书审批：公告期将自动发起飞书原生审批，部门负责人在飞书中完成审批，结果自动回写台账（负责人收到的是审批待办，不再另发提醒卡片）。"
          />
        )}

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

          <Form.Item
            name="sign_page_base_url"
            label="签字页基地址"
            extra="员工线上签字 H5 页地址（如 https://hr.example.com/api/contract-sign）；为空时签字提醒不带链接"
          >
            <Input maxLength={200} allowClear />
          </Form.Item>

          <Form.Item name="contact_info" label="通知联系人文案" extra="员工侧通知卡片中的联系人（默认「人力资源部」）">
            <Input maxLength={64} allowClear />
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
