'use client'

// 交付证明与签收（第 5 步）。系统只部署在公司内网，员工在手机 / 外网打不开任何指向本系统的
// 链接，所以没有「线上签字」：证明用邮件发或当面递交，员工签字二选一——
//   ① 到人事办公室，在这台公司电脑上手写签名（签名图随档案留存）；
//   ② 在纸质证明上签字后，HR 登记签收（时间 / 签收人留存）。
// 短信没有接服务商：文案由 HR 复制后用手机 / 飞书发给员工，再回来登记「已发送」。

import { useState } from 'react'
import {
  Alert, App as AntdApp, Button, Input, Popconfirm, Space, Steps, Tag, Typography, type StepsProps,
} from 'antd'
import { DownloadOutlined, EditOutlined } from '@ant-design/icons'
import type { OffboardingCaseDetail } from '@/types/hr'
import {
  downloadOffboardingCertificate,
  paperSignOffboardingCase,
  registerOffboardingSms,
  resendOffboardingDelivery,
} from '@/actions/hr'
import { copyText, downloadBase64File, renderSmsText, smsStatusMeta } from '@/lib/hr'
import CasePanel, { fmtTime } from './CasePanel'

const { Text } = Typography

type Busy = 'mail' | 'sms' | 'paper' | 'download' | null

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type StepStatus = 'error' | 'finish' | 'process' | 'wait'

/** 步骤状态按字面量类型给，否则三元表达式会被推成 string、对不上 Steps 的类型 */
const finishOrProcess = (done: boolean): StepStatus => (done ? 'finish' : 'process')

export default function DeliveryPanel({
  detail,
  notes,
  onNotesChange,
  onOpenSignature,
  onChanged,
}: {
  detail: OffboardingCaseDetail
  /** 没办成的事（开证时邮件失败等）：留在面板顶部逐条提醒，HR 处理完再关 */
  notes: string[]
  onNotesChange: (notes: string[]) => void
  /** 打开「员工手写签名」弹窗（员工在这台电脑上签） */
  onOpenSignature: () => void
  onChanged: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  // 本面板只在「证明送达中」阶段挂载，初值取自详情即可（状态变化会重新挂载）
  const [mailRecipient, setMailRecipient] = useState(detail.mail_recipient || detail.employee_email || '')
  const [smsPhone, setSmsPhone] = useState(detail.sms_phone || detail.employee_phone || '')
  const [signedBy, setSignedBy] = useState(detail.name)
  const [busy, setBusy] = useState<Busy>(null)

  const smsText = renderSmsText(detail.sms_template, detail.contact)
  const sms = smsStatusMeta(detail.sms_status)

  const sendMail = async () => {
    const recipient = mailRecipient.trim()
    if (!recipient) {
      message.warning('请填写收件邮箱')
      return
    }
    if (!EMAIL_PATTERN.test(recipient)) {
      message.warning('请输入正确的收件邮箱地址')
      return
    }
    setBusy('mail')
    try {
      const res = await resendOffboardingDelivery(detail.id, { mail_recipient: recipient })
      // 成了的用轻提示报一声；没成的原因进面板顶部的提醒条（这次成了的旧提醒一并清掉）
      const parts = (res.message || '').split('；').filter((part) => part && part !== '邮件已发送')
      if (res.data?.mail_status === 'sent') {
        message.success('邮件已发送')
        onNotesChange(parts)
      } else {
        onNotesChange(parts.length ? parts : ['邮件发送失败，请检查系统设置里的邮件服务器信息'])
      }
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '发送邮件失败')
    } finally {
      setBusy(null)
    }
  }

  const registerSms = async () => {
    const phone = smsPhone.trim()
    if (!phone) {
      message.warning('请填写接收短信的手机号')
      return
    }
    setBusy('sms')
    try {
      await registerOffboardingSms(detail.id, phone)
      message.success('已登记短信发送')
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '登记短信失败')
    } finally {
      setBusy(null)
    }
  }

  const copySms = async () => {
    if (!smsText) {
      message.warning('短信文案还没配置，请到「系统配置 → 离职管理」填写')
      return
    }
    // 内网的 http 地址不是安全上下文，navigator.clipboard 可能不存在：copyText 自带兜底
    const ok = await copyText(smsText)
    if (ok) message.success('短信文案已复制')
    else message.warning('复制失败，请手动选中短信文案复制')
  }

  const paperSign = async () => {
    const name = signedBy.trim()
    if (!name) {
      message.warning('请填写签收人姓名')
      return
    }
    setBusy('paper')
    try {
      await paperSignOffboardingCase(detail.id, { signed_by: name })
      message.success('签收已登记，可以办结了')
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '登记签收失败')
    } finally {
      setBusy(null)
    }
  }

  const download = async () => {
    setBusy('download')
    try {
      const file = await downloadOffboardingCertificate(detail.id, detail.case_no)
      downloadBase64File(file.base64, file.filename)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '下载证明失败')
    } finally {
      setBusy(null)
    }
  }

  const mailTag = !detail.mail_recipient
    ? <Tag>未发送</Tag>
    : detail.mail_status === 'sent'
      ? <Tag color="success">已发送 {fmtTime(detail.mail_sent_at)}</Tag>
      : <Tag color="error">发送失败</Tag>
  const smsTag = sms.sent
    ? <Tag color="success">{sms.label} {fmtTime(detail.sms_sent_at)}</Tag>
    : <Tag>{sms.label}</Tag>

  // 两步：交给员工（邮件 / 短信可按需选）→ 员工签收（必做）。办结要等签收完成
  const stepItems: NonNullable<StepsProps['items']> = [
    {
      key: 'deliver',
      title: '把证明交给员工（邮件、短信按需，也可当面递交）',
      status: finishOrProcess(detail.mail_status === 'sent' || sms.sent),
      content: (
        <div className="space-y-2 pt-1">
          <Space wrap>
            <span className="text-[13px] text-[var(--color-ink)]">邮件</span>
            {mailTag}
            <Input
              type="email"
              value={mailRecipient}
              onChange={(e) => setMailRecipient(e.target.value)}
              placeholder="员工本人邮箱"
              maxLength={128}
              style={{ width: 240 }}
              allowClear
              aria-label="送达邮箱"
            />
            <Button loading={busy === 'mail'} onClick={() => void sendMail()}>
              发送邮件（附证明 PDF）
            </Button>
          </Space>
          <div className="text-[12px] text-[var(--color-steel)]">
            邮箱取自入职台账登记的本人邮箱，可改；发送失败会在这里说明原因
          </div>
          <Space wrap>
            <span className="text-[13px] text-[var(--color-ink)]">短信</span>
            {smsTag}
            <Input
              value={smsPhone}
              onChange={(e) => setSmsPhone(e.target.value)}
              placeholder="员工手机号"
              maxLength={32}
              style={{ width: 180 }}
              allowClear
              aria-label="短信接收手机号"
            />
            <Button onClick={() => void copySms()}>复制短信文案</Button>
            <Button loading={busy === 'sms'} onClick={() => void registerSms()}>
              登记已发送
            </Button>
          </Space>
          <div className="text-[12px] text-[var(--color-steel)]">
            短信需要人工发：复制文案后用手机短信或飞书发给员工，再点「登记已发送」留下发送时间
          </div>
        </div>
      ),
    },
    {
      key: 'sign',
      title: '员工签收（二选一，办结前必须完成）',
      status: 'wait',
      content: (
        <div className="space-y-2 pt-1">
          <div className="rounded-[var(--rounded-md)] bg-[var(--color-surface)] px-3 py-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Button type="primary" icon={<EditOutlined />} onClick={onOpenSignature}>
                员工手写签名
              </Button>
              <span className="text-[13px] text-[var(--color-ink)]">员工到人事办公室时，在这台电脑上签名</span>
            </div>
            <Text className="block text-[12px] leading-[1.6] text-[var(--color-steel)]">
              让员工本人用手指、触控笔或鼠标签名，签名图随离职档案留存。电子单张版建议用这种方式。
            </Text>
          </div>
          <Space wrap>
            <Button icon={<DownloadOutlined />} loading={busy === 'download'} onClick={() => void download()}>
              下载证明 PDF
            </Button>
            <Input
              value={signedBy}
              onChange={(e) => setSignedBy(e.target.value)}
              placeholder="签收人（员工本人）"
              maxLength={64}
              style={{ width: 180 }}
              aria-label="签收人"
            />
            <Popconfirm
              title="登记纸质签收？"
              description="登记后进入「已签收」。请确认员工已在纸质证明上签字。"
              okText="登记签收"
              cancelText="取消"
              onConfirm={() => void paperSign()}
              disabled={busy !== null}
            >
              <Button loading={busy === 'paper'}>登记纸质签收</Button>
            </Popconfirm>
          </Space>
          <Text className="block text-[12px] text-[var(--color-steel)]">
            员工已在打印出来的证明上签字（纸质两联版在签收栏签字）时，在这里登记签收人与时间。
          </Text>
        </div>
      ),
    },
  ]

  return (
    <CasePanel
      step={5}
      tone="warning"
      title="交付证明并签收"
      hint="把证明交给员工，员工签字后在这里登记签收；签收完成才能办结。"
      extra={<Tag color="processing">待员工签收</Tag>}
    >
      {notes.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable
          title="有几件事没办成，需要处理"
          description={
            <ul className="m-0 list-disc space-y-0.5 pl-5">
              {notes.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          }
          onClose={() => onNotesChange([])}
        />
      )}
      <Steps orientation="vertical" size="small" items={stepItems} />
    </CasePanel>
  )
}
