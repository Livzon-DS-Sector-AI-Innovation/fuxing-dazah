'use client'

// 办结收尾（第 6 步）：员工签字确认后，由 HR 确认「飞书账号已注销」并办结。
// 办结是唯一改写员工档案状态的节点，一次联动五处；平台不自动操作飞书账号，只登记 HR 的确认。

import { useState } from 'react'
import { App as AntdApp, Button, Popconfirm, Switch } from 'antd'
import type { OffboardingCaseDetail } from '@/types/hr'
import { closeOffboardingCase } from '@/actions/hr'
import CasePanel, { fmtTime } from './CasePanel'

const LINKAGES = [
  '员工档案：用工状态置为离职，回写离职日期与离职原因',
  '证件档案：当前版本转为历史保留（不删除，仍可查看）',
  '培训花名册：同步为离职，不再出现在培训选人里',
  '入职台账：用工状态置为不在职',
  '离职台账：回写办结结果（离职日期 / 类型 / 原因、证明开具与签收）',
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
  const signWay = detail.delivery_channel === 'paper'
    ? '纸质当面签收'
    : signed?.has_sign_image ? '线上手写签名' : '线上确认'

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
      step={6}
      tone="warning"
      title="办结收尾"
      hint={`员工已于 ${fmtTime(signedAt)} ${signWay}${signed?.cert_sign_name ? `（签署人 ${signed.cert_sign_name}）` : ''}。确认账号已注销后办结。`}
    >
      <ul className="m-0 list-disc space-y-1 pl-5 text-[13px] leading-[1.6] text-[var(--color-slate)]">
        {LINKAGES.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <Switch checked={deactivated} onChange={setDeactivated} aria-label="飞书账号已注销" />
        <span className="text-[13px] text-[var(--color-ink)]">飞书账号已注销</span>
      </div>
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
