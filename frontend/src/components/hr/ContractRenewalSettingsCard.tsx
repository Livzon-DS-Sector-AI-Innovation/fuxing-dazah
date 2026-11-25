'use client'

// 劳动合同续签流程配置（系统配置 →「劳动合同」页签）：
// 总开关 / 公告期提前天数 / 飞书审批定义编码 / HR 抄送 / 签字页地址 / 联系人文案。
// 配置存 hr.system_settings（hr_contract.*），后端定时任务与审批发起前读取；
// 审批定义为空时部门审批自动降级为站内台账勾选（无需定义即可上线）。

import { useEffect, useState } from 'react'
import { App, Alert, Button, Card, Form, Input, InputNumber, Switch } from 'antd'
import { getSystemSettings, updateSystemSettings } from '@/actions/hr'

interface ContractSettingsFormValues {
  renewal_pipeline_enabled: boolean
  announcement_days_ahead: number | null
  renewal_approval_code: string
  hr_copy_open_ids: string
  sign_page_base_url: string
  contact_info: string
}

const KEYS = {
  enabled: 'hr_contract.renewal_pipeline_enabled',
  days: 'hr_contract.announcement_days_ahead',
  approvalCode: 'hr_contract.renewal_approval_code',
  hrCopy: 'hr_contract.hr_copy_open_ids',
  signBase: 'hr_contract.sign_page_base_url',
  contact: 'hr_contract.contact_info',
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
          renewal_approval_code: str(KEYS.approvalCode),
          hr_copy_open_ids: str(KEYS.hrCopy),
          sign_page_base_url: str(KEYS.signBase),
          contact_info: str(KEYS.contact),
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
        [KEYS.approvalCode]: values.renewal_approval_code?.trim() ?? '',
        [KEYS.hrCopy]: values.hr_copy_open_ids?.trim() ?? '',
        [KEYS.signBase]: values.sign_page_base_url?.trim().replace(/\/+$/, '') ?? '',
        [KEYS.contact]: values.contact_info?.trim() ?? '',
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
        {!approvalCode && (
          <Alert
            type="info"
            showIcon
            message="未配置飞书审批定义：部门审批将走站内台账勾选（同意/不同意）。"
            description="如需飞书原生审批，请在飞书审批后台创建「劳动合同续签审批」定义（流程节点设为「发起人自选审批人」，表单控件名：姓名、工号、部门、岗位、原合同到期日、本次签订类型、合同期限、合同起始日期、备注），并将定义编码填到下方。"
          />
        )}

        <Form<ContractSettingsFormValues> form={form} layout="vertical" onFinish={(v) => void save(v)}>
          <Form.Item name="renewal_pipeline_enabled" label="续签流程总开关" valuePropName="checked">
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>

          <Form.Item
            name="announcement_days_ahead"
            label="公告期提前天数"
            extra="到期前 N 天进入公告期：自动发起部门审批并通知（需求默认 50 天）"
          >
            <InputNumber min={1} max={365} style={{ width: 160 }} />
          </Form.Item>

          <Form.Item
            name="renewal_approval_code"
            label="飞书审批定义编码"
            extra="为空时降级站内勾选审批；配置后公告期自动发起飞书原生审批"
          >
            <Input maxLength={64} placeholder="如 7C468A54-8745-2245-9675-08B7C63E7A85" allowClear />
          </Form.Item>

          <Form.Item
            name="hr_copy_open_ids"
            label="HR 抄送（姓名或 open_id，逗号分隔）"
            extra="公告期扫描摘要、到期未续签清单发送给这些接收人"
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

          <Button type="primary" htmlType="submit" loading={saving}>
            保存配置
          </Button>
        </Form>
      </div>
    </Card>
  )
}
