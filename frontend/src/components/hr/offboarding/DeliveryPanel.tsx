'use client'

// 送达与签收（第 5 步）。电子版：邮件送达 + 签署链接，员工线上手写签名后自动推进；
// 纸质两联版：登记当面签收。短信通道尚未接入——手机号只做登记，签署链接由 HR 复制转发。
// 签署链接由抽屉持有（跨面板保留）：开具证明时拿到的链接进到本面板仍然有效，
// 不必重新生成——重新生成会让 HR 已经发出去的链接作废。

import { useState } from 'react'
import {
  App as AntdApp, Button, Divider, Input, Popconfirm, Space, Tag, Typography,
} from 'antd'
import { DownloadOutlined, LinkOutlined, MailOutlined, MobileOutlined } from '@ant-design/icons'
import type { OffboardingCaseDetail } from '@/types/hr'
import {
  downloadOffboardingCertificate,
  paperSignOffboardingCase,
  resendOffboardingDelivery,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import CasePanel, { fmtTime } from './CasePanel'

const { Text } = Typography

type Busy = 'mail' | 'sms' | 'paper' | 'download' | null

export default function DeliveryPanel({
  detail,
  signUrl,
  onSignUrlChange,
  onOpenLink,
  onChanged,
}: {
  detail: OffboardingCaseDetail
  /** 当前有效的签署链接（抽屉持有；null = 还没生成过） */
  signUrl: string | null
  onSignUrlChange: (url: string | null) => void
  /** 打开链接弹窗（重新生成的动作在弹窗里） */
  onOpenLink: () => void
  onChanged: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  // 本面板只在「证明送达中」阶段挂载，初值取自详情即可（状态变化会重新挂载）
  const electronic = detail.cert_template !== 'paper'
  const [mailRecipient, setMailRecipient] = useState(detail.mail_recipient || '')
  const [smsPhone, setSmsPhone] = useState(detail.sms_phone || '')
  const [signedBy, setSignedBy] = useState(detail.name)
  const [busy, setBusy] = useState<Busy>(null)

  /** 补发的统一出口：后端把说明（失败原因、通道未接入）拼在 message 里 */
  const deliver = async (kind: Busy, payload: { mail_recipient?: string; sms_phone?: string }) => {
    setBusy(kind)
    try {
      const res = await resendOffboardingDelivery(detail.id, payload)
      message.info(res.message || '送达处理完成', 6)
      if (res.data?.sign_url) onSignUrlChange(res.data.sign_url)
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '送达处理失败')
    } finally {
      setBusy(null)
    }
  }

  const sendMail = async () => {
    const recipient = mailRecipient.trim()
    if (!recipient) {
      message.warning('请填写收件邮箱')
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
      message.warning('请输入正确的收件邮箱地址')
      return
    }
    await deliver('mail', { mail_recipient: recipient })
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
      message.success('纸质签收已登记')
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

  return (
    <CasePanel
      step={5}
      tone="warning"
      title="送达与签收"
      hint={
        electronic
          ? '把证明和签署链接送达员工；员工在签字页手写签名后，这里自动更新为「已签字确认」。'
          : '打印纸质两联交员工当面签字；签收后在此登记签收人与时间。'
      }
      extra={<Tag color="processing">{electronic ? '电子单张版' : '纸质两联版'}</Tag>}
    >
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-[var(--color-slate)]">
        <MailOutlined />
        邮件 {mailTag}
        {detail.sms_status && (
          <>
            <MobileOutlined className="ml-2" />
            短信 {detail.sms_phone}
            <Tag>
              {detail.sms_status === 'sent' ? '已发送' : detail.sms_status === 'not_configured' ? '通道未接入' : '失败'}
            </Tag>
          </>
        )}
      </div>

      {electronic && (
        <div className="space-y-1">
          <div className="text-[13px] font-medium text-[var(--color-ink)]">签署链接</div>
          <Space wrap>
            <Button type="primary" icon={<LinkOutlined />} onClick={onOpenLink}>
              {signUrl ? '查看签署链接' : '生成签署链接'}
            </Button>
            <span className="text-[12px] text-[var(--color-slate)]">
              短信通道未接入：生成后复制链接，用微信 / 短信等转发给员工；员工签字后链接自动失效
            </span>
          </Space>
        </div>
      )}

      <Divider titlePlacement="left" className="!my-2">
        <span className="text-[13px] font-medium text-[var(--color-ink)]">邮件</span>
      </Divider>
      <Space wrap>
        <Input
          type="email"
          value={mailRecipient}
          onChange={(e) => setMailRecipient(e.target.value)}
          placeholder="员工邮箱"
          maxLength={128}
          style={{ width: 260 }}
          allowClear
        />
        <Button icon={<MailOutlined />} loading={busy === 'mail'} onClick={() => void sendMail()}>
          {electronic ? '发送邮件（附证明与签署链接）' : '发送邮件（附证明）'}
        </Button>
        {electronic && (
          <span className="text-[12px] text-[var(--color-steel)]">重发会换新的签署链接，旧链接作废</span>
        )}
      </Space>

      <Divider titlePlacement="left" className="!my-2">
        <span className="text-[13px] font-medium text-[var(--color-ink)]">短信</span>
      </Divider>
      <Space wrap>
        <Input
          value={smsPhone}
          onChange={(e) => setSmsPhone(e.target.value)}
          placeholder="员工手机号"
          maxLength={32}
          style={{ width: 200 }}
          allowClear
        />
        <Button loading={busy === 'sms'} onClick={() => void deliver('sms', { sms_phone: smsPhone.trim() || undefined })}>
          登记短信送达
        </Button>
        <span className="text-[12px] text-[var(--color-steel)]">短信服务商确定前仅登记号码，不会真的发送</span>
      </Space>

      <Divider titlePlacement="left" className="!my-2">
        <span className="text-[13px] font-medium text-[var(--color-ink)]">签收</span>
      </Divider>
      <Space wrap align="start">
        <Button icon={<DownloadOutlined />} loading={busy === 'download'} onClick={() => void download()}>
          下载证明 PDF
        </Button>
        <Input
          value={signedBy}
          onChange={(e) => setSignedBy(e.target.value)}
          placeholder="签收人（员工本人）"
          maxLength={64}
          style={{ width: 200 }}
        />
        <Popconfirm
          title="登记当面签收？"
          description="登记后进入「已签字确认」，请确认员工已在纸质证明上签字。"
          okText="登记签收"
          cancelText="取消"
          onConfirm={() => void paperSign()}
          disabled={busy !== null}
        >
          <Button danger={electronic} loading={busy === 'paper'}>
            登记纸质签收
          </Button>
        </Popconfirm>
      </Space>
      {electronic && (
        <Text className="block text-[12px] text-[var(--color-steel)]">
          电子版通常由员工在线签字；员工无法线上签字时，也可以打印后走当面签收。
        </Text>
      )}
    </CasePanel>
  )
}
