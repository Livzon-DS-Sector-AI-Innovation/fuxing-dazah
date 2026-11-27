'use client'

// 员工当面手写签名：员工到人事办公室，在 HR 登录的这台公司电脑上（触屏 / 触控笔 / 鼠标）签名。
// 系统只部署在公司内网，员工在手机 / 外网打不开指向本系统的链接，所以签字不走外部链接；
// 提交后签名图随离职档案留存（签收方式 = 当面手写签名），办理单进入待办结。

import { useState } from 'react'
import { Alert, App as AntdApp, Input, Modal } from 'antd'
import type { OffboardingCaseDetail } from '@/types/hr'
import { signOffboardingSignature } from '@/actions/hr'
import SignaturePad from './SignaturePad'

export default function SignatureModal({
  open,
  detail,
  onClose,
  onChanged,
}: {
  open: boolean
  detail: OffboardingCaseDetail
  onClose: () => void
  /** 签名提交成功后刷新详情 */
  onChanged: () => Promise<void>
}) {
  // 不渲染 = 完全卸载：每次打开都是干净的签名板，不会留着上一次的笔迹
  if (!open) return null
  return <SignForm detail={detail} onClose={onClose} onChanged={onChanged} />
}

function SignForm({
  detail,
  onClose,
  onChanged,
}: {
  detail: OffboardingCaseDetail
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const { message } = AntdApp.useApp()
  const [signature, setSignature] = useState<string | null>(null)
  const [signedName, setSignedName] = useState(detail.name)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    const name = signedName.trim()
    if (!signature) {
      message.warning('请员工先在签名区手写签名')
      return
    }
    if (!name) {
      message.warning('请填写签署人姓名')
      return
    }
    setBusy(true)
    try {
      await signOffboardingSignature(detail.id, { signature, signed_name: name })
      message.success('员工已签名确认，可以办结了')
      await onChanged()
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '签名提交失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="员工手写签名"
      open
      okText="提交签名"
      cancelText="取消"
      onOk={() => void submit()}
      onCancel={onClose}
      okButtonProps={{ loading: busy }}
      width={680}
    >
      <div className="space-y-3 pt-1">
        <Alert
          type="info"
          showIcon
          title="请员工本人在这台电脑上签名"
          description="让员工用手指、触控笔或鼠标在下方签名。提交后签名图随离职档案留存，办理单进入待办结。"
        />
        <div>
          <div className="mb-1 text-[13px] font-medium text-[var(--color-ink)]">签署人</div>
          <Input
            value={signedName}
            onChange={(e) => setSignedName(e.target.value)}
            maxLength={64}
            aria-label="签署人姓名"
          />
        </div>
        <SignaturePad onChange={setSignature} height={220} />
      </div>
    </Modal>
  )
}
