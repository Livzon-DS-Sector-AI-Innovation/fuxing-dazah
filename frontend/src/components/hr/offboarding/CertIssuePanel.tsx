'use client'

// 核对并开具解除劳动关系证明（第 4 步）。两种模板对应两种签收方式：
//   电子单张版 → PDF 邮件送达 + 一次性签署链接，员工在 H5 手写签名；
//   纸质两联版 → 打印后交员工当面签字，下一步登记签收。
// 证明里的姓名 / 身份证号 / 入职日期自档案带出，开具前必须能预览核对。

import { useState } from 'react'
import { Alert, App as AntdApp, Button, Descriptions, Input, Popconfirm, Segmented, Space } from 'antd'
import { EyeOutlined, PrinterOutlined } from '@ant-design/icons'
import type { OffboardingCaseDetail, OffboardingCaseDeliveryResponse } from '@/types/hr'
import { issueOffboardingCertificate, previewOffboardingCertificate } from '@/actions/hr'
import CasePanel from './CasePanel'

type Template = 'electronic' | 'paper'

export default function CertIssuePanel({
  detail,
  onChanged,
  onIssued,
}: {
  detail: OffboardingCaseDetail
  /** 开具成功后刷新详情 */
  onChanged: () => Promise<void>
  /** 开具成功：把响应交回抽屉（带签署链接时直接弹链接窗，趁热交给 HR） */
  onIssued: (data: OffboardingCaseDeliveryResponse) => void
}) {
  const { message } = AntdApp.useApp()
  const [template, setTemplate] = useState<Template>('electronic')
  const [mailRecipient, setMailRecipient] = useState('')
  const [busy, setBusy] = useState(false)

  const preview = async () => {
    // 先同步开窗再取数：await 之后的 window.open 不算用户手势，会被浏览器拦截
    const win = window.open('', '_blank')
    if (!win) {
      message.warning('浏览器拦截了预览窗口，请允许本站弹出窗口后重试')
      return
    }
    try {
      win.document.write(await previewOffboardingCertificate(detail.id, template))
      win.document.close()
    } catch (err) {
      win.close()
      message.error(err instanceof Error ? err.message : '预览失败')
    }
  }

  const issue = async () => {
    const recipient = mailRecipient.trim()
    if (recipient && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
      message.warning('请输入正确的收件邮箱地址')
      return
    }
    setBusy(true)
    try {
      const res = await issueOffboardingCertificate(detail.id, {
        cert_template: template,
        mail_recipient: recipient || undefined,
      })
      // 后端把提示（没填邮箱 / 邮件失败 / 没配签字页地址）拼在 message 的分号后面
      const [head, ...rest] = (res.message || '').split('；')
      if (rest.length) message.warning(`${head}；${rest.join('；')}`, 8)
      else message.success(head || '证明已开具')
      onIssued(res.data)
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '开具证明失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <CasePanel
      step={4}
      tone="warning"
      title="核对并开具解除劳动关系证明"
      hint="证明内容自档案带出。请先预览核对姓名、身份证号、入职日期、部门岗位、离职日期与原因，再选择模板开具。"
    >
      <Descriptions
        size="small"
        bordered
        column={2}
        items={[
          { key: 'name', label: '姓名', children: detail.name },
          { key: 'dept', label: '部门 / 岗位', children: `${detail.department} / ${detail.position || '-'}` },
          { key: 'date', label: '离职日期', children: detail.offboarding_date },
          { key: 'reason', label: '离职原因', children: detail.reason || detail.offboarding_type },
        ]}
      />

      <div className="space-y-1">
        <div className="text-[13px] font-medium text-[var(--color-ink)]">证明模板</div>
        <Segmented
          block
          value={template}
          onChange={(v) => setTemplate(v as Template)}
          options={[
            { value: 'electronic', label: '电子单张版（线上签收）', icon: <EyeOutlined /> },
            { value: 'paper', label: '纸质两联版（当面签收）', icon: <PrinterOutlined /> },
          ]}
        />
        <p className="m-0 text-[12px] leading-[1.5] text-[var(--color-slate)]">
          {template === 'electronic'
            ? '开具后进入送达环节：证明 PDF 与签署链接发到员工邮箱（也可不开邮件，稍后复制签署链接转发），员工打开链接手写签名确认。'
            : '开具后进入送达环节：打印两联交员工当面签字，公司留存联归档、员工留存联交员工，然后登记当面签收。'}
        </p>
      </div>

      {template === 'electronic' && (
        <div className="space-y-1">
          <div className="text-[13px] font-medium text-[var(--color-ink)]">送达邮箱（可选）</div>
          <Space.Compact className="w-full">
            <Input
              type="email"
              value={mailRecipient}
              onChange={(e) => setMailRecipient(e.target.value)}
              placeholder="填写后开具即自动发送；留空则之后在送达环节补发"
              maxLength={128}
              allowClear
            />
          </Space.Compact>
        </div>
      )}

      <Alert type="info" showIcon title="开具后证明文件即归档，内容不可再修改；如需更正请先取消本次办理后重新发起。" />

      <Space wrap>
        <Button icon={<EyeOutlined />} onClick={() => void preview()}>
          预览证明
        </Button>
        <Popconfirm
          title="确认开具证明？"
          description="开具后进入送达环节，证明 PDF 归档。"
          okText="开具"
          cancelText="再核对一下"
          onConfirm={() => void issue()}
          disabled={busy}
        >
          <Button type="primary" loading={busy}>
            核对无误，开具证明
          </Button>
        </Popconfirm>
      </Space>
    </CasePanel>
  )
}
