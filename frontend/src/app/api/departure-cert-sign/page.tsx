'use client'

// 离职证明签字确认页（免登）：放在 app/api/ 静态段下复用 proxy.ts 的公开路径白名单。
// next.config 把 /api/:path* rewrite 到后端，且该规则先于动态路由段生效，所以这里必须是
// 静态段 + ?token= 查询参数（动态段 [token] 会被 rewrite 抢走，已验证 404）。
//
// 员工经邮件 / 短信里的链接打开（离职办结后飞书账号随即注销，这是主要签署入口），
// 多半在手机上：查看证明 → 核对姓名 → 手写签名 → 提交。token 一次性，提交后链接即失效，
// 所以签字成功页的「下载证明」用的是确认接口随响应带回的 PDF，不再依赖 token。

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Alert, App as AntdApp, Button, Card, Input, Skeleton, Space, Typography } from 'antd'
import { CheckCircleOutlined, DownloadOutlined, EditOutlined } from '@ant-design/icons'
import type { DepartureCertSignResult, DepartureCertSignView } from '@/types/hr'
import { downloadBase64File } from '@/lib/hr'
import CertificateFrame from '@/components/hr/offboarding/CertificateFrame'
import SignaturePad from '@/components/hr/offboarding/SignaturePad'

const { Text, Title } = Typography
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL

function SignForm({ token }: { token: string }) {
  const { message } = AntdApp.useApp()
  const [view, setView] = useState<DepartureCertSignView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [signature, setSignature] = useState<string | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const [signing, setSigning] = useState(false)
  const [result, setResult] = useState<DepartureCertSignResult | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/hr/departure-cert-sign/${encodeURIComponent(token)}`, {
          cache: 'no-store',
        })
        const body = await res.json().catch(() => null)
        if (cancelled) return
        if (!res.ok) throw new Error(body?.message || '签字链接无效或已失效')
        const data = body.data as DepartureCertSignView
        setView(data)
        setConfirmName(data.name || '')
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败，请稍后重试')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [token])

  /** 签字前 token 仍有效，直接走下载接口 */
  const downloadBefore = () => {
    window.location.href = `${API_BASE}/api/v1/hr/departure-cert-sign/${encodeURIComponent(token)}/pdf`
  }

  /** 签字后 token 已作废：用确认接口随响应带回的 PDF 内容下载 */
  const downloadAfter = (pdfBase64: string, filename: string) => downloadBase64File(pdfBase64, filename)

  const confirm = async () => {
    if (!signature) {
      message.warning('请先在签名区手写签名')
      return
    }
    if (!confirmName.trim()) {
      message.warning('请填写您的姓名')
      return
    }
    setSigning(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/departure-cert-sign/${encodeURIComponent(token)}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signature, confirm_name: confirmName.trim() }),
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.message || '签字提交失败，请重试')
      setResult(body.data as DepartureCertSignResult)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '签字提交失败')
    } finally {
      setSigning(false)
    }
  }

  if (loading) return <Skeleton active paragraph={{ rows: 6 }} />
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        title="无法打开签字页"
        description={`${error}。如需帮助请联系人力资源部。`}
      />
    )
  }
  if (!view) return null

  const contact = view.contact || '人力资源部'

  if (result) {
    const pdf = result.has_pdf ? result.pdf_base64 : null
    return (
      <div className="space-y-4">
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          title="签字确认成功"
          description="您的签名已存档，本链接已失效。可点击下方按钮留存一份证明。"
        />
        {pdf ? (
          <Button
            type="primary"
            size="large"
            block
            icon={<DownloadOutlined />}
            onClick={() => downloadAfter(pdf, result.pdf_filename || '解除劳动关系证明.pdf')}
          >
            下载解除劳动关系证明（PDF）
          </Button>
        ) : (
          <Alert type="info" showIcon title="证明文件请联系人力资源部领取" />
        )}
        <Text className="block text-center text-[13px] text-[var(--color-steel)]">
          如对证明内容有疑问，请联系{contact}。
        </Text>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <Title level={4} className="!mt-0 !mb-1">
          {view.name}
        </Title>
        <Text className="text-[13px] text-[var(--color-slate)]">
          {view.department} / {view.position} · 离职日期 {view.leave_date || '—'}
        </Text>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[13px] font-medium text-[var(--color-ink)]">解除劳动关系证明</span>
          {view.has_pdf && (
            <Button size="small" icon={<DownloadOutlined />} onClick={downloadBefore}>
              下载 PDF
            </Button>
          )}
        </div>
        <CertificateFrame html={view.certificate_html} />
      </div>

      <Alert
        type="info"
        showIcon
        title="请核对以上内容"
        description="手写签名并提交，即表示您已收到《解除劳动关系证明》且对内容无异议；签名将与离职档案一并存档。链接仅可使用一次，提交后自动失效。"
      />

      <div>
        <div className="mb-1 text-[13px] font-medium text-[var(--color-ink)]">您的姓名</div>
        <Input
          value={confirmName}
          onChange={(e) => setConfirmName(e.target.value)}
          prefix={<EditOutlined />}
          placeholder="请输入本人姓名"
          maxLength={64}
          size="large"
        />
      </div>

      <SignaturePad onChange={setSignature} />

      <Space direction="vertical" size="small" className="w-full">
        <Button
          type="primary"
          size="large"
          block
          loading={signing}
          disabled={!signature}
          onClick={() => void confirm()}
        >
          确认签字并提交
        </Button>
        <Text className="block text-center text-[12px] text-[var(--color-steel)]">
          如对证明内容有疑问，请先联系{contact}，暂勿签字。
        </Text>
      </Space>
    </div>
  )
}

/** 读取 token 并选择渲染内容（必须整体包在 Suspense 内：useSearchParams 会触发 CSR bailout） */
function SignContent() {
  const searchParams = useSearchParams()
  const token = (searchParams.get('token') || '').trim()

  if (!token) return <Alert type="error" showIcon title="签字链接无效（缺少凭证）" />
  return <SignForm token={token} />
}

export default function DepartureCertSignPage() {
  return (
    <div className="min-h-screen bg-[var(--color-surface)] px-3 py-4 sm:flex sm:items-start sm:justify-center sm:p-6">
      <Card
        className="w-full max-w-2xl"
        title="解除劳动关系证明 · 签字确认"
        styles={{ body: { padding: 16 } }}
      >
        <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
          <SignContent />
        </Suspense>
      </Card>
    </div>
  )
}
