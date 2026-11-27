'use client'

// 办结收尾（最后一步）：员工签收后（到人事办公室在公司电脑上手写签名，或纸质签收登记），
// HR 在飞书侧注销账号、在这里勾选确认并办结。
// 办结是唯一改写员工档案状态的节点，一次联动多处；平台不自动操作飞书账号，只登记 HR 的确认。

import { useState } from 'react'
import { App as AntdApp, Button, Checkbox, Popconfirm } from 'antd'
import type { OffboardingCaseDetail } from '@/types/hr'
import { closeOffboardingCase } from '@/actions/hr'
import { signWayLabel } from '@/lib/hr'
import CasePanel, { fmtTime } from './CasePanel'
import SignatureImage from './SignatureImage'

const LINKAGES = [
  '员工档案：用工状态置为离职，回写离职日期与离职原因',
  '证件档案：当前版本转为历史保留（不删除，仍可查看）',
  '培训花名册：同步为离职，不再出现在培训选人里',
  '入职台账：用工状态置为不在职',
  '离职台账：回写办结结果（离职日期 / 类型 / 原因、证明开具与签收）',
  '劳动合同：名下未完结的合同置为已终止，不再进入到期预警与续签提醒',
]

export default function ClosePanel({
  detail,
  onChanged,
}: {
  detail: OffboardingCaseDetail
  onChanged: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  // 默认不勾：这是 HR 对「账号已在飞书侧注销」的确认，必须本人勾选
  const [deactivated, setDeactivated] = useState(false)
  const [busy, setBusy] = useState(false)

  const signed = detail.sign_state
  const signedAt = detail.paper_signed_at || signed?.cert_signed_at
  const signWay = signWayLabel(detail.delivery_channel)

  const close = async () => {
    setBusy(true)
    try {
      await closeOffboardingCase(detail.id, { account_deactivated: deactivated })
      message.success('已办结，档案与各台账已同步')
      await onChanged()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '办结失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <CasePanel
      step={7}
      stepLabel="最后一步"
      tone="warning"
      title="办结收尾"
      hint={`员工已于 ${fmtTime(signedAt)} ${signWay}${signed?.cert_sign_name ? `（签收人 ${signed.cert_sign_name}）` : ''}。注销账号后办结。`}
    >
      <SignatureImage caseId={detail.id} />

      <div className="text-[13px] font-medium text-[var(--color-ink)]">办结后系统自动完成</div>
      <ul className="m-0 list-disc space-y-1 pl-5 text-[13px] leading-[1.6] text-[var(--color-slate)]">
        {LINKAGES.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>

      <Checkbox checked={deactivated} onChange={(e) => setDeactivated(e.target.checked)}>
        我已在飞书管理后台注销该员工的账号
      </Checkbox>

      <Popconfirm
        title="确认办结？"
        description="办结后员工档案与各台账同步更新，不可撤销。"
        okText="确认办结"
        cancelText="取消"
        onConfirm={() => void close()}
        disabled={busy || !deactivated}
      >
        <Button type="primary" loading={busy} disabled={!deactivated}>
          确认办结
        </Button>
      </Popconfirm>
    </CasePanel>
  )
}
