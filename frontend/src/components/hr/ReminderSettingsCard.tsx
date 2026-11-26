'use client'

// 人事提醒配置（系统配置 →「提醒配置」页签）：转正/合同到期提醒的接收人、开关、提前天数。
// 配置存后端 system_settings KV（hr_reminder.contract_expiry.* 与旧键
// probation_reminder.open_ids），定时任务每天运行前读取：
// 转正提醒 09:00（提前 7 天固定）、合同到期提醒 09:10（提前天数可配）。
// 接收人按「姓名」保存，发送时由后端解析成 open_id（同名多人不发送）——所以提供「发送测试」
// 让配置的人能确认卡片确实送得到。

import { useEffect, useState } from 'react'
import { App, Alert, Button, Card, Divider, Form, InputNumber, Space, Spin, Switch } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { getSystemSettings, sendReminderTest, updateSystemSettings } from '@/actions/hr'
import ReceiverSelect from './ReceiverSelect'

interface ReminderFormValues {
  /** 存姓名（后端发送时解析为 open_id）；也允许直接粘贴 open_id */
  probation_receivers: string[]
  contract_enabled: boolean
  contract_days_ahead: number | null
  contract_receivers: string[]
}

const DEFAULT_DAYS_AHEAD = 30
const splitReceivers = (v: string) => v.split(',').map(s => s.trim()).filter(Boolean)

export function ReminderSettingsCard() {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<ReminderFormValues>()
  const [initial, setInitial] = useState<ReminderFormValues | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingKind, setTestingKind] = useState<'probation' | 'contract' | null>(null)

  // 配置取回后再挂载表单并用 initialValues 回填：
  // 此前 Card loading 期间 Form 还没挂载就 setFieldsValue，控制台报「useForm 实例未连接到任何 Form」
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getSystemSettings()
        if (cancelled) return
        const kv = (res.data || {}) as Record<string, unknown>
        const str = (k: string) => (typeof kv[k] === 'string' ? (kv[k] as string) : '')
        const days = parseInt(str('hr_reminder.contract_expiry.days_ahead'), 10)
        setInitial({
          probation_receivers: splitReceivers(str('probation_reminder.open_ids')),
          contract_enabled: str('hr_reminder.contract_expiry.enabled') !== 'false',
          contract_days_ahead: Number.isFinite(days) && days > 0 ? days : DEFAULT_DAYS_AHEAD,
          contract_receivers: splitReceivers(str('hr_reminder.contract_expiry.open_ids')),
        })
      } catch (e: unknown) {
        message.error(e instanceof Error ? e.message : '加载提醒配置失败')
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = async (values: ReminderFormValues) => {
    setSaving(true)
    try {
      await updateSystemSettings({
        // 存储格式保持「逗号分隔的姓名/open_id」，与定时任务读取口径一致
        'probation_reminder.open_ids': (values.probation_receivers || []).join(','),
        'hr_reminder.contract_expiry.enabled': values.contract_enabled ? 'true' : 'false',
        'hr_reminder.contract_expiry.days_ahead': String(values.contract_days_ahead ?? DEFAULT_DAYS_AHEAD),
        'hr_reminder.contract_expiry.open_ids': (values.contract_receivers || []).join(','),
      })
      message.success('提醒配置已保存（次日定时任务生效）')
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 发一张测试卡片，把「送得到 / 无法解析 / 发送失败」如实告诉配置的人 */
  const handleTest = async (kind: 'probation' | 'contract') => {
    const field = kind === 'probation' ? 'probation_receivers' : 'contract_receivers'
    const receivers = (form.getFieldValue(field) as string[] | undefined) || []
    if (!receivers.length) { message.warning('请先选择这一项的接收人'); return }
    setTestingKind(kind)
    try {
      const r = await sendReminderTest({ kind, receivers })
      const d = r.data
      const kindLabel = kind === 'probation' ? '转正提醒' : '合同到期提醒'
      modal.info({
        title: `「${kindLabel}」测试消息已发送`,
        width: 520,
        content: (
          <div className="space-y-2">
            <div>已送达 <b>{d.sent}</b> 位接收人，请对方查看飞书。</div>
            {d.unresolved.length > 0 && (
              <Alert
                type="warning" showIcon
                title={`${d.unresolved.length} 位接收人无法解析，不会收到提醒`}
                description={`无法解析：${d.unresolved.join('、')}。常见原因：同名多人、姓名写错、或对方从未登录过系统。可改为填写其 open_id。`}
              />
            )}
            {d.failed.length > 0 && (
              <Alert
                type="error" showIcon
                title={`${d.failed.length} 位接收人发送失败`}
                description={d.failed.map(f => `${f.receiver}：${f.error}`).join('；')}
              />
            )}
            {d.sent > 0 && d.unresolved.length === 0 && d.failed.length === 0 && (
              <div className="text-[var(--color-steel)]">配置无误，正式提醒会按设定时间自动发送。</div>
            )}
          </div>
        ),
      })
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '发送测试消息失败')
    } finally {
      setTestingKind(null)
    }
  }

  return (
    // 页签名已是「提醒配置」，卡片不再重复标题
    <Card className="max-w-2xl">
      {!initial ? (
        <div className="py-8 text-center"><Spin /></div>
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            title="定时提醒经飞书卡片推送给接收人。接收人从在职员工里选择；留空则不推送（仅在服务端日志记录）。保存前可先「发送测试」确认卡片送得到。"
          />
          <Form form={form} layout="vertical" initialValues={initial} onFinish={handleSave}>
            <Divider titlePlacement="left">转正提醒（每天 09:00，试用期到期前 7 天）</Divider>
            <Form.Item
              name="probation_receivers"
              label="接收人"
              extra="同名多人的员工无法按姓名定位，系统不会发送；请改填其 open_id"
            >
              <ReceiverSelect />
            </Form.Item>
            <div className="mb-4">
              <Button icon={<SendOutlined />} loading={testingKind === 'probation'} onClick={() => void handleTest('probation')}>
                发送测试
              </Button>
            </div>

            <Divider titlePlacement="left">合同到期提醒（每天 09:10）</Divider>
            <Form.Item name="contract_enabled" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
            <Form.Item
              name="contract_days_ahead"
              label="提前提醒天数（天）"
              extra="合同结束日期距今天数在该窗口内（含已过期未续签）时提醒"
            >
              {/* 单位写进 label：antd 6 已弃用 InputNumber 的 addonAfter（控制台告警） */}
              <InputNumber min={1} max={365} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="contract_receivers" label="接收人">
              <ReceiverSelect />
            </Form.Item>

            <Space>
              <Button type="primary" htmlType="submit" loading={saving}>保存配置</Button>
              <Button icon={<SendOutlined />} loading={testingKind === 'contract'} onClick={() => void handleTest('contract')}>
                发送测试
              </Button>
            </Space>
          </Form>
        </>
      )}
    </Card>
  )
}
