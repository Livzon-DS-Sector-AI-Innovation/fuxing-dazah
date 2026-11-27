'use client'

// 离职管理配置（系统配置 →「离职管理」页签）。配置存后端 system_settings KV，
// 后端在发起审批、开具证明和定时任务运行前读取：
// - hr_offboarding.*                        审批定义编码（按职级分轨）/ 通知 / 提前天数 / 清退清单 / 短信文案
// - hr_reminder.offboarding_lead.*          离职发起时限提醒（每天 09:20）
// - hr_reminder.offboarding_clearance_due.* 离职手续催办（每天 09:30）
// 全部可缺省：不配任何审批定义也能跑，审批环节走「站内登记办结」。
// 系统只部署在公司内网，员工在手机 / 外网打不开本系统的链接：没有签字页地址之类的配置，
// 员工签收到人事办公室在公司电脑上手写签名，或在纸质件上签字后登记。

import { useEffect, useState } from 'react'
import { Alert, App as AntdApp, Button, Card, Divider, Form, Input, InputNumber, Space, Spin, Switch } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { getSystemSettings, sendReminderTest, updateSystemSettings } from '@/actions/hr'
import type { ClearanceCategory } from '@/types/hr'
import ReceiverSelect from './ReceiverSelect'

const KEYS = {
  resignStaff: 'hr_offboarding.resignation_approval_code_staff',
  resignDirector: 'hr_offboarding.resignation_approval_code_director',
  clearanceStaff: 'hr_offboarding.clearance_approval_code_staff',
  clearanceDirector: 'hr_offboarding.clearance_approval_code_director',
  directorLevels: 'hr_offboarding.director_levels',
  hrCopy: 'hr_offboarding.hr_copy_open_ids',
  contact: 'hr_offboarding.contact_info',
  leadResigned: 'hr_offboarding.lead_warn_days_resigned',
  leadProbation: 'hr_offboarding.lead_warn_days_probation',
  clearanceItems: 'hr_offboarding.clearance_items',
  smsTemplate: 'hr_offboarding.sms_template',
  leadEnabled: 'hr_reminder.offboarding_lead.enabled',
  leadReceivers: 'hr_reminder.offboarding_lead.open_ids',
  leadAhead: 'hr_reminder.offboarding_lead.days_ahead',
  clearanceEnabled: 'hr_reminder.offboarding_clearance_due.enabled',
  clearanceReceivers: 'hr_reminder.offboarding_clearance_due.open_ids',
} as const

const DEFAULTS = { resigned: 30, probation: 3, leadAhead: 7 }

const CLEARANCE_KEYS: ClearanceCategory[] = ['admin', 'finance', 'hr', 'work']
const CLEARANCE_LABELS: Record<ClearanceCategory, string> = {
  admin: '行政后勤部', finance: '财务部', hr: '人力资源部', work: '工作部门',
}
// 需求列明的默认清单；配置留空时后端就用这份
const CLEARANCE_DEFAULTS: Record<ClearanceCategory, string> = {
  admin: '宿舍钥匙\n寝室个人物品\n饭卡余额\n通信补贴\n车辆通行证\n办公室钥匙\n工本费',
  finance: '电脑等电子设备\nU盘\n个人欠款',
  hr: '社保医保公积金\n厂牌考勤卡\n培训费\n违约金\n工资结算至',
  work: '业务往来\n考勤统计\n劳保用品\n工作服\n岗位技术资料',
}
// 短信只做通知、不带链接（员工在手机上打不开本系统的链接）
const DEFAULT_SMS_TEMPLATE =
  '你好，我是丽珠福兴人力资源部{联系人}，您的离职证明已经开具，请您到人力资源部签收。'

type TestKind = 'offboarding_lead' | 'offboarding_clearance_due'
const TEST_LABEL: Record<TestKind, string> = {
  offboarding_lead: '离职发起时限提醒',
  offboarding_clearance_due: '离职手续催办',
}

type ClearanceItemsText = Record<ClearanceCategory, string>

interface FormValues {
  resignation_approval_code_staff: string
  resignation_approval_code_director: string
  clearance_approval_code_staff: string
  clearance_approval_code_director: string
  director_levels: string
  hr_copy_open_ids: string[]
  contact_info: string
  lead_warn_days_resigned: number | null
  lead_warn_days_probation: number | null
  clearance_items: ClearanceItemsText
  sms_template: string
  lead_enabled: boolean
  lead_receivers: string[]
  lead_days_ahead: number | null
  clearance_enabled: boolean
  clearance_receivers: string[]
}

const splitReceivers = (value: unknown): string[] =>
  typeof value === 'string' ? value.split(',').map((s) => s.trim()).filter(Boolean) : []

/** 清退清单文本 → 事项数组：换行、逗号、顿号、分号都当分隔符 */
const itemLines = (text: string): string[] =>
  text.split(/[\n，,、;；]+/).map((s) => s.trim()).filter(Boolean)

/** 库里的清退清单 JSON → 四个部门的文本框内容；没配或配坏了都给空（= 用默认清单） */
function parseClearanceItems(raw: unknown): ClearanceItemsText {
  const empty: ClearanceItemsText = { admin: '', finance: '', hr: '', work: '' }
  if (typeof raw !== 'string' || !raw.trim()) return empty
  try {
    const obj = JSON.parse(raw) as Record<string, unknown> | null
    return Object.fromEntries(CLEARANCE_KEYS.map((key) => [
      key, Array.isArray(obj?.[key]) ? (obj[key] as unknown[]).join('\n') : '',
    ])) as ClearanceItemsText
  } catch {
    return empty
  }
}

/** 文本框内容 → 库里的 JSON；四个部门都没填就存空串（= 恢复默认清单） */
function serializeClearanceItems(value: ClearanceItemsText): string {
  const obj = Object.fromEntries(
    CLEARANCE_KEYS.map((key) => [key, itemLines(value[key] || '')]).filter(([, items]) => items.length),
  )
  return Object.keys(obj).length ? JSON.stringify(obj) : ''
}

function positiveInt(value: unknown, fallback: number): number {
  const parsed = parseInt(typeof value === 'string' ? value : '', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

/** 哪些审批环节接了飞书（按编码是否填写判断），决定页首的说明文案 */
function configuredStages(values: Pick<FormValues,
  'resignation_approval_code_staff' | 'resignation_approval_code_director'
  | 'clearance_approval_code_staff' | 'clearance_approval_code_director'>) {
  return {
    resignation: Boolean(values.resignation_approval_code_staff.trim() || values.resignation_approval_code_director.trim()),
    clearance: Boolean(values.clearance_approval_code_staff.trim() || values.clearance_approval_code_director.trim()),
  }
}

export default function OffboardingSettingsCard() {
  const { message, modal } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()
  const [initial, setInitial] = useState<FormValues | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingKind, setTestingKind] = useState<TestKind | null>(null)
  const [stages, setStages] = useState({ resignation: false, clearance: false })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getSystemSettings()
        if (cancelled) return
        const kv = (res.data || {}) as Record<string, unknown>
        const text = (key: string) => (typeof kv[key] === 'string' ? (kv[key] as string) : '')
        const values: FormValues = {
          resignation_approval_code_staff: text(KEYS.resignStaff),
          resignation_approval_code_director: text(KEYS.resignDirector),
          clearance_approval_code_staff: text(KEYS.clearanceStaff),
          clearance_approval_code_director: text(KEYS.clearanceDirector),
          director_levels: text(KEYS.directorLevels),
          hr_copy_open_ids: splitReceivers(kv[KEYS.hrCopy]),
          contact_info: text(KEYS.contact),
          lead_warn_days_resigned: positiveInt(kv[KEYS.leadResigned], DEFAULTS.resigned),
          lead_warn_days_probation: positiveInt(kv[KEYS.leadProbation], DEFAULTS.probation),
          clearance_items: parseClearanceItems(kv[KEYS.clearanceItems]),
          sms_template: text(KEYS.smsTemplate),
          lead_enabled: text(KEYS.leadEnabled) !== 'false',
          lead_receivers: splitReceivers(kv[KEYS.leadReceivers]),
          lead_days_ahead: positiveInt(kv[KEYS.leadAhead], DEFAULTS.leadAhead),
          clearance_enabled: text(KEYS.clearanceEnabled) !== 'false',
          clearance_receivers: splitReceivers(kv[KEYS.clearanceReceivers]),
        }
        setStages(configuredStages(values))
        setInitial(values)
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载离职管理配置失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (values: FormValues) => {
    setSaving(true)
    try {
      await updateSystemSettings({
        [KEYS.resignStaff]: values.resignation_approval_code_staff.trim(),
        [KEYS.resignDirector]: values.resignation_approval_code_director.trim(),
        [KEYS.clearanceStaff]: values.clearance_approval_code_staff.trim(),
        [KEYS.clearanceDirector]: values.clearance_approval_code_director.trim(),
        [KEYS.directorLevels]: values.director_levels.trim(),
        [KEYS.hrCopy]: values.hr_copy_open_ids.join(','),
        [KEYS.contact]: values.contact_info.trim(),
        [KEYS.leadResigned]: String(values.lead_warn_days_resigned ?? DEFAULTS.resigned),
        [KEYS.leadProbation]: String(values.lead_warn_days_probation ?? DEFAULTS.probation),
        [KEYS.clearanceItems]: serializeClearanceItems(values.clearance_items),
        [KEYS.smsTemplate]: values.sms_template.trim(),
        [KEYS.leadEnabled]: values.lead_enabled ? 'true' : 'false',
        [KEYS.leadReceivers]: values.lead_receivers.join(','),
        [KEYS.leadAhead]: String(values.lead_days_ahead ?? DEFAULTS.leadAhead),
        [KEYS.clearanceEnabled]: values.clearance_enabled ? 'true' : 'false',
        [KEYS.clearanceReceivers]: values.clearance_receivers.join(','),
      })
      setStages(configuredStages(values))
      message.success('已保存')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 发一张测试卡片，把「送得到 / 无法解析 / 发送失败」如实告诉配置的人 */
  const handleTest = async (kind: TestKind) => {
    const field = kind === 'offboarding_lead' ? 'lead_receivers' : 'clearance_receivers'
    const receivers = (form.getFieldValue(field) as string[] | undefined) || []
    if (!receivers.length) {
      message.warning('请先选择这一项的接收人')
      return
    }
    setTestingKind(kind)
    try {
      const res = await sendReminderTest({ kind, receivers })
      const data = res.data
      modal.info({
        title: `「${TEST_LABEL[kind]}」测试消息已发送`,
        width: 520,
        content: (
          <div className="space-y-2">
            <div>已送达 <b>{data.sent}</b> 位接收人，请对方查看飞书。</div>
            {data.unresolved.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`${data.unresolved.length} 位接收人无法解析，不会收到提醒`}
                description={`无法解析：${data.unresolved.join('、')}。常见原因：同名多人、姓名写错、或对方从未登录过系统。可改为填写其 open_id。`}
              />
            )}
            {data.failed.length > 0 && (
              <Alert
                type="error"
                showIcon
                title={`${data.failed.length} 位接收人发送失败`}
                description={data.failed.map((f) => `${f.receiver}：${f.error}`).join('；')}
              />
            )}
          </div>
        ),
      })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '发送测试消息失败')
    } finally {
      setTestingKind(null)
    }
  }

  return (
    <Card className="max-w-3xl">
      {!initial ? (
        <div className="py-8 text-center"><Spin /></div>
      ) : (
        <Form<FormValues> form={form} layout="vertical" initialValues={initial} onFinish={(values) => void save(values)}>
          <Alert
            type={stages.resignation || stages.clearance ? 'info' : 'success'}
            showIcon
            style={{ marginBottom: 16 }}
            title={
              stages.resignation && stages.clearance
                ? '离职审批与清退会签均已接飞书审批'
                : stages.resignation || stages.clearance
                  ? `已接飞书审批：${[stages.resignation && '离职审批', stages.clearance && '清退会签'].filter(Boolean).join('、')}；其余环节走站内登记`
                  : '审批当前在系统内办理（默认方式），无需额外配置'
            }
            description={
              stages.resignation || stages.clearance
                ? '填了编码的环节在发起后自动创建飞书审批，办结后约 15 分钟内自动推进；没填的环节由 HR 在办理抽屉里「登记办结」。'
                : 'HR 发起后，部门负责人线下审批，审批通过后在办理抽屉里「登记办结」即可推进。'
            }
          />

          <Divider titlePlacement="left">飞书审批（可选增强）</Divider>
          <Form.Item
            name="resignation_approval_code_staff"
            label="离职审批 · 一般员工至 M4"
            extra="留空 = 站内登记办结"
          >
            <Input maxLength={64} placeholder="飞书审批定义编码" allowClear />
          </Form.Item>
          <Form.Item
            name="resignation_approval_code_director"
            label="离职审批 · M5 及以上（总监级）"
            extra="留空 = 该职级也走站内登记办结"
          >
            <Input maxLength={64} placeholder="飞书审批定义编码" allowClear />
          </Form.Item>
          <Form.Item
            name="clearance_approval_code_staff"
            label="清退交接 · 一般员工至 M4"
            extra="部门审批办结后，到建议发起日（离职日前 2 天）自动发起；留空 = 站内登记各部门清退情况"
          >
            <Input maxLength={64} placeholder="飞书审批定义编码" allowClear />
          </Form.Item>
          <Form.Item
            name="clearance_approval_code_director"
            label="清退交接 · M5 及以上（总监级）"
            extra="留空 = 该职级也走站内登记"
          >
            <Input maxLength={64} placeholder="飞书审批定义编码" allowClear />
          </Form.Item>
          <Form.Item
            name="director_levels"
            label="总监级职级前缀（逗号分隔）"
            extra="职级以这些前缀开头的员工走「M5 及以上」那一套审批；其余走一般员工那一套"
          >
            <Input maxLength={128} placeholder="M5,M6,M7,M8" allowClear />
          </Form.Item>
          <Alert
            type="info"
            style={{ marginBottom: 16 }}
            title="审批定义的控件名约定（人事在飞书审批后台按名称创建）"
            description={
              <ul className="m-0 list-disc space-y-1 pl-5">
                <li>流程节点须设为「发起人自选审批人」。</li>
                <li>离职审批表单控件：姓名、工号、部门、岗位、职级、离职日期、离职类型、离职原因、备注。</li>
                <li>清退交接表单控件：姓名、工号、部门、岗位、离职日期、备注，另加各部门的多行文本「行政后勤清退事项」「财务清退事项」「人力资源清退事项」「工作部门清退事项」——每行一条：事项名称｜状态｜扣款｜补发｜备注；会签办结后自动回读成清退明细。</li>
                <li>控件缺失不会报错，缺的部分由 HR 在平台手工登记。</li>
              </ul>
            }
          />

          <Divider titlePlacement="left">清退事项清单</Divider>
          <div className="mb-3 text-[12px] text-[var(--color-steel)]">
            进入清退会签时，每个部门自带这里的清单，HR 逐项确认。一项一行；留空 = 用需求列明的默认清单。
          </div>
          <Space size="large" wrap align="start">
            {CLEARANCE_KEYS.map((key) => (
              <Form.Item key={key} name={['clearance_items', key]} label={CLEARANCE_LABELS[key]}>
                <Input.TextArea
                  rows={7}
                  style={{ width: 200 }}
                  placeholder={CLEARANCE_DEFAULTS[key]}
                  aria-label={`${CLEARANCE_LABELS[key]}清退事项`}
                />
              </Form.Item>
            ))}
          </Space>

          <Divider titlePlacement="left">证明与送达</Divider>
          <Form.Item
            name="contact_info"
            label="联系人"
            extra="写在员工通知和短信里，填具体的人名，如「王琳」；留空只显示「人力资源部」"
          >
            <Input maxLength={64} placeholder="王琳" allowClear />
          </Form.Item>
          <Form.Item
            name="sms_template"
            label="离职证明短信文案"
            extra="短信需要 HR 复制后用手机或飞书发出，只做通知。占位符 {联系人} 会换成上面的联系人；留空用下面的默认文案"
          >
            <Input.TextArea rows={3} maxLength={300} placeholder={DEFAULT_SMS_TEMPLATE} allowClear />
          </Form.Item>

          <Divider titlePlacement="left">通知</Divider>
          <Form.Item
            name="hr_copy_open_ids"
            label="流程通知接收人"
            extra="阶段推进、飞书审批发起失败等通知发给这些 HR；留空则不推送"
          >
            <ReceiverSelect />
          </Form.Item>

          <Divider titlePlacement="left">发起时限</Divider>
          <Space size="large" wrap>
            <Form.Item name="lead_warn_days_probation" label="试用期员工须提前（天）">
              <InputNumber min={1} max={365} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="lead_warn_days_resigned" label="转正员工须提前（天）">
              <InputNumber min={1} max={365} style={{ width: 140 }} />
            </Form.Item>
          </Space>
          <div className="mb-4 text-[12px] text-[var(--color-steel)]">
            发起审批时距离职日不足这个天数会给出提示（不拦截，协商离职等情形可继续）。
          </div>

          <Divider titlePlacement="left">离职发起时限提醒（每天 09:20）</Divider>
          <Form.Item name="lead_enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item
            name="lead_days_ahead"
            label="距应发起日不足多少天开始提醒（天）"
            extra="档案已定离职日、但还没发起离职办理的员工，临近应发起日时提醒；已超期的持续提醒"
          >
            <InputNumber min={1} max={60} style={{ width: 140 }} />
          </Form.Item>
          <Form.Item name="lead_receivers" label="接收人" extra="部门负责人会一并收到">
            <ReceiverSelect />
          </Form.Item>
          <Button
            className="mb-4"
            icon={<SendOutlined />}
            loading={testingKind === 'offboarding_lead'}
            onClick={() => void handleTest('offboarding_lead')}
          >
            发送测试
          </Button>

          <Divider titlePlacement="left">离职手续催办（每天 09:30）</Divider>
          <Form.Item name="clearance_enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item
            name="clearance_receivers"
            label="接收人"
            extra="距离职日已不足 2 天、仍停在离职审批或清退会签的办结单会被催办；部门负责人会一并收到"
          >
            <ReceiverSelect />
          </Form.Item>
          <Button
            className="mb-4"
            icon={<SendOutlined />}
            loading={testingKind === 'offboarding_clearance_due'}
            onClick={() => void handleTest('offboarding_clearance_due')}
          >
            发送测试
          </Button>

          <Button type="primary" htmlType="submit" loading={saving}>
            保存配置
          </Button>
        </Form>
      )}
    </Card>
  )
}
