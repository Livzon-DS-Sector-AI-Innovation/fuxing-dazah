'use client'

// 核对并开具解除劳动关系证明（第 4 步）。两种模板只差版式，签收方式相同：
//   电子单张版 → 单张 PDF，可邮件发给员工；
//   纸质两联版 → 含员工签收栏，打印后交员工当面签字。
// 系统只部署在公司内网，员工在手机上打不开任何指向本系统的链接，所以没有「线上签收」：
// 员工到人事办公室时在公司电脑上手写签名，或在纸质件上签字后登记。
// 证明里的姓名 / 身份证号 / 入职日期自档案带出，开具前必须能预览核对。

import { useState } from 'react'
import { Alert, App as AntdApp, Button, Descriptions, Input, Modal, Popconfirm, Segmented, Space } from 'antd'
import { EyeOutlined, PrinterOutlined } from '@ant-design/icons'
import type { OffboardingCase, OffboardingCaseDetail } from '@/types/hr'
import { issueOffboardingCertificate, previewOffboardingCertificate } from '@/actions/hr'
import CasePanel from './CasePanel'
import CertificateFrame, { A4_HEIGHT } from './CertificateFrame'

type Template = 'electronic' | 'paper'

export default function CertIssuePanel({
  detail,
  onChanged,
  onIssued,
}: {
  detail: OffboardingCaseDetail
  /** 开具成功后刷新详情 */
  onChanged: () => Promise<void>
  /** 开具成功：把响应交回抽屉；没办成的事（邮件失败等）由抽屉留在下一步的交付面板里提醒 */
  onIssued: (data: OffboardingCase, notes: string[]) => void
}) {
  const { message } = AntdApp.useApp()
  const [template, setTemplate] = useState<Template>('electronic')
  const [mailRecipient, setMailRecipient] = useState('')
  const [busy, setBusy] = useState(false)
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)

  const preview = async () => {
    setPreviewing(true)
    try {
      // 页内弹窗预览，不开新窗口：浏览器普遍拦弹窗，不熟的同事不知道怎么放行
      setPreviewHtml(await previewOffboardingCertificate(detail.id, template))
    } catch (err) {
      message.error(err instanceof Error ? err.message : '预览失败')
    } finally {
      setPreviewing(false)
    }
  }

  /** 预览窗里直接开具：看过全文再点的「确认无误」，不再叠一层确认 */
  const issueFromPreview = () => {
    setPreviewHtml(null)
    void issue()
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
      // 后端把没办成的事（邮件失败 / 没配签字页地址等）拼在 message 的分号后面：
      // 这里只报「已开具」，缘由逐条留在下一步的送达面板里，免得轻提示一闪而过没人看清
      const [head, ...notes] = (res.message || '').split('；')
      message.success(head || '证明已开具')
      onIssued(res.data, notes)
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
            { value: 'electronic', label: '电子单张版（可发邮件）', icon: <EyeOutlined /> },
            { value: 'paper', label: '纸质两联版（含签收栏）', icon: <PrinterOutlined /> },
          ]}
        />
        <p className="m-0 text-[12px] leading-[1.5] text-[var(--color-slate)]">
          {template === 'electronic'
            ? '单张 PDF。可邮件发给员工；员工到人事办公室时在这台电脑上手写签名，或打印后签字登记。'
            : '打印两联交员工在签收栏当面签字：公司留存联归档、员工留存联交员工，然后登记签收。'}
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
        <Button icon={<EyeOutlined />} loading={previewing} onClick={() => void preview()}>
          预览证明
        </Button>
        <Popconfirm
          title="确认开具证明？"
          description="还没预览的话建议先预览核对一遍。开具后进入送达环节，证明 PDF 归档。"
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

      <Modal
        open={previewHtml !== null}
        onCancel={() => setPreviewHtml(null)}
        title="证明预览 · 开具前核对"
        width={856}
        // antd v6：内容盒的语义键是 container（v5 叫 content）；留出 794px 纸面 + 竖滚动条的宽度
        styles={{ container: { padding: '16px 16px 12px' }, body: { padding: 0 } }}
        footer={[
          <Button key="close" onClick={() => setPreviewHtml(null)}>关闭</Button>,
          <Button key="issue" type="primary" loading={busy} onClick={issueFromPreview}>
            确认无误，开具证明
          </Button>,
        ]}
      >
        <p className="m-0 mb-2 text-[12px] leading-[1.6] text-[var(--color-slate)]">
          下方就是将要开具的证明{template === 'paper' ? '（两联）' : ''}。内容有误请先关闭本窗口，取消本次办理、更正档案后重新发起。
        </p>
        <CertificateFrame
          html={previewHtml || ''}
          height={template === 'paper' ? 2 * A4_HEIGHT : A4_HEIGHT}
          viewportHeight="68vh"
        />
      </Modal>
    </CasePanel>
  )
}
