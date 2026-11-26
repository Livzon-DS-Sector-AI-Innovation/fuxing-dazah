'use client'

// 离职管理配置（系统配置 →「离职管理」页签）。配置存后端 system_settings KV，
// 后端在发起审批、开具证明和定时任务运行前读取：
// - hr_offboarding.*                        审批定义编码（按职级分轨）/ 签字页地址 / 通知 / 提前天数
// - hr_reminder.offboarding_lead.*          离职发起时限提醒（每天 09:20）
// - hr_reminder.offboarding_clearance_due.* 离职手续催办（每天 09:30）
// 全部可缺省：不配任何审批定义也能跑，审批环节走「站内登记办结」。

import { useEffect, useState } from 'react'
import { Alert, App as AntdApp, Button, Card, Divider, Form, Input, InputNumber, Space, Spin, Switch } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { getSystemSettings, sendReminderTest, updateSystemSettings } from '@/actions/hr'
import ReceiverSelect from './ReceiverSelect'

const KEYS = {
  resignStaff: 'hr_offboarding.resignation_approval_code_staff',
  resignDirector: 'hr_offboarding.resignation_approval_code_director',
  clearanceStaff: 'hr_offboarding.clearance_approval_code_staff',
  clearanceDirector: 'hr_offboarding.clearance_approval_code_director',
  directorLevels: 'hr_offboarding.director_levels',
  signBase: 'hr_offboarding.sign_page_base_url',
  hrCopy: 'hr_offboarding.hr_copy_open_ids',
  contact: 'hr_offboarding.contact_info',
  leadResigned: 'hr_offboarding.lead_warn_days_resigned',
  leadProbation: 'hr_offboarding.lead_warn_days_probation',
  leadEnabled: 'hr_reminder.offboarding_lead.enabled',
  leadReceivers: 'hr_reminder.offboarding_lead.open_ids',
  leadAhead: 'hr_reminder.offboarding_lead.days_ahead',
  clearanceEnabled: 'hr_reminder.offboarding_clearance_due.enabled',
  clearanceReceivers: 'hr_reminder.offboarding_clearance_due.open_ids',
} as const

const DEFAULTS = { resigned: 30, probation: 3, leadAhead: 7 }
const SIGN_PAGE_PATH = '/api/departure-cert-sign'

type TestKind = 'offboarding_lead' | 'offboarding_clearance_due'
const TEST_LABEL: Record<TestKind, string> = {
  offboarding_lead: '离职发起时限提醒',
  offboarding_clearance_due: '离职手续催办',
}

interface FormValues {
  resignation_approval_code_staff: string
  resignation_approval_code_director: string
  clearance_approval_code_staff: string
  clearance_approval_code_director: string
  director_levels: string
  sign_page_base_url: string
  hr_copy_open_ids: string[]
  contact_info: string
  lead_warn_days_resigned: number | null
  lead_warn_days_probation: number | null
  lead_enabled: boolean
  lead_receivers: string[]
  lead_days_ahead: number | null
  clearance_enabled: boolean
  clearance_receivers: string[]
}

const splitReceivers = (value: unknown): string[] =>
  typeof value === 'string' ? value.split(',').map((s) => s.trim()).filter(Boolean) : []

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
          sign_page_base_url: text(KEYS.signBase),
          hr_copy_open_ids: splitReceivers(kv[KEYS.hrCopy]),
          contact_info: text(KEYS.contact),
          lead_warn_days_resigned: positiveInt(kv[KEYS.leadResigned], DEFAULTS.resigned),
          lead_warn_days_probation: positiveInt(kv[KEYS.leadProbation], DEFAULTS.probation),
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
        [KEYS.signBase]: values.sign_page_base_url.trim().replace(/\/+$/, ''),
        [KEYS.hrCopy]: values.hr_copy_open_ids.join(','),
        [KEYS.contact]: values.contact_info.trim(),
        [KEYS.leadResigned]: String(values.lead_warn_days_resigned ?? DEFAULTS.resigned),
        [KEYS.leadProbation]: String(values.lead_warn_days_probation ?? DEFAULTS.probation),
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

  const fillSignBase = () => {
    form.setFieldValue('sign_page_base_url', `${window.location.origin}${SIGN_PAGE_PATH}`)
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
            extra="离职审批办结后自动发起；留空 = 站内登记各部门清退情况"
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

          <Divider titlePlacement="left">证明签署</Divider>
          <Form.Item
            name="sign_page_base_url"
            label="签字页地址"
            extra="员工在签字页查看证明并手写签名；没填的话开具证明时生成不了签署链接"
          >
            <Input maxLength={200} placeholder={`如 https://hr.example.com${SIGN_PAGE_PATH}`} allowClear />
          </Form.Item>
          <Button className="mb-4" onClick={fillSignBase}>
            填入本站地址
          </Button>

          <Divider titlePlacement="left">通知</Divider>
          <Form.Item
            name="hr_copy_open_ids"
            label="流程通知接收人"
            extra="阶段推进、飞书审批发起失败等通知发给这些 HR；留空则不推送"
          >
            <ReceiverSelect />
          </Form.Item>
          <Form.Item name="contact_info" label="通知联系人文案" extra="员工侧通知与短信落款处的联系人">
            <Input maxLength={64} placeholder="人力资源部" allowClear />
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
