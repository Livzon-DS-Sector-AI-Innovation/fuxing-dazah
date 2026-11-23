'use client'

// 人事提醒配置卡片：转正/合同到期提醒的接收人、开关、提前天数。
// 配置存后端 system_settings KV（hr_reminder.contract_expiry.* 与旧键
// probation_reminder.open_ids），定时任务每天运行前读取：
// 转正提醒 09:00（提前 7 天固定）、合同到期提醒 09:10（提前天数可配）。
// 接收人填姓名或 open_id，多个用英文逗号分隔（姓名自动解析，同名多人不发送）。

import { useEffect, useState } from 'react'
import { App, Alert, Button, Card, Divider, Form, Input, InputNumber, Switch } from 'antd'
import { getSystemSettings, updateSystemSettings } from '@/actions/hr'

interface ReminderFormValues {
  probation_receivers: string
  contract_enabled: boolean
  contract_days_ahead: number | null
  contract_receivers: string
}

const DEFAULT_DAYS_AHEAD = 30

export function ReminderSettingsCard() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getSystemSettings()
        if (cancelled) return
        const kv = (res.data || {}) as Record<string, unknown>
        const str = (k: string) => (typeof kv[k] === 'string' ? (kv[k] as string) : '')
        const days = parseInt(str('hr_reminder.contract_expiry.days_ahead'), 10)
        form.setFieldsValue({
          probation_receivers: str('probation_reminder.open_ids'),
          contract_enabled: str('hr_reminder.contract_expiry.enabled') !== 'false',
          contract_days_ahead: Number.isFinite(days) && days > 0 ? days : DEFAULT_DAYS_AHEAD,
          contract_receivers: str('hr_reminder.contract_expiry.open_ids'),
        })
      } catch (e: unknown) {
        message.error(e instanceof Error ? e.message : '加载提醒配置失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = async (values: ReminderFormValues) => {
    setSaving(true)
    try {
      await updateSystemSettings({
        'probation_reminder.open_ids': values.probation_receivers.trim(),
        'hr_reminder.contract_expiry.enabled': values.contract_enabled ? 'true' : 'false',
        'hr_reminder.contract_expiry.days_ahead': String(values.contract_days_ahead ?? DEFAULT_DAYS_AHEAD),
        'hr_reminder.contract_expiry.open_ids': values.contract_receivers.trim(),
      })
      message.success('提醒配置已保存（次日定时任务生效）')
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="人事提醒配置" loading={loading} className="max-w-xl">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="定时提醒经飞书卡片推送给接收人；接收人填姓名或 open_id，多个用英文逗号分隔。留空则不推送（仅在服务端日志记录）。"
      />
      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Divider titlePlacement="left">转正提醒（每天 09:00，试用期到期前 7 天）</Divider>
        <Form.Item
          name="probation_receivers"
          label="接收人"
          extra="例：张三,ou_xxxxxxxx（姓名自动解析，同名多人不发送）"
        >
          <Input placeholder="接收人姓名或 open_id，多个用英文逗号分隔" allowClear />
        </Form.Item>

        <Divider titlePlacement="left">合同到期提醒（每天 09:10）</Divider>
        <Form.Item name="contract_enabled" label="启用" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>
        <Form.Item
          name="contract_days_ahead"
          label="提前提醒天数"
          extra="合同结束日期距今天数在该窗口内（含已过期未续签）时提醒"
        >
          <InputNumber min={1} max={365} style={{ width: 140 }} addonAfter="天" />
        </Form.Item>
        <Form.Item name="contract_receivers" label="接收人">
          <Input placeholder="接收人姓名或 open_id，多个用英文逗号分隔" allowClear />
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={saving}>保存配置</Button>
      </Form>
    </Card>
  )
}
