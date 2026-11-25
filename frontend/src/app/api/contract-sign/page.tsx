'use client'

// 员工线上签字确认页（免登）：放在 app/api/ 静态段下复用 proxy.ts 的 PUBLIC_PATHS
// 白名单（/login、/auth/callback、/api），员工点飞书卡片「点击签字」直达，无需系统账号。
// 注意 next.config.ts 把 /api/:path* rewrite 到后端，且 afterFiles 规则先于动态路由段生效，
// 所以这里必须用静态段 + ?token= 查询参数（动态段 [token] 会被 rewrite 抢走，已验证 404）。
// token 即凭证：一次性，确认成功后后端清空 token，链接自动作废。

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Alert, Button, Card, Descriptions, Skeleton, Space } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ContractSignView } from '@/types/hr'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL

function SignForm({ token }: { token: string }) {
  const [view, setView] = useState<ContractSignView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/hr/contract-sign/${token}`, { cache: 'no-store' })
        const body = await res.json()
        if (cancelled) return
        if (!res.ok) throw new Error(body?.message || '签字链接无效或已失效')
        setView(body.data as ContractSignView)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [token])

  const confirm = async () => {
    setConfirming(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/contract-sign/${token}/confirm`, { method: 'POST' })
      const body = await res.json()
      if (!res.ok) throw new Error(body?.message || '签字失败')
      setView(body.data as ContractSignView)
    } catch (e) {
      setError(e instanceof Error ? e.message : '签字失败')
    } finally {
      setConfirming(false)
    }
  }

  if (loading) return <Skeleton active />

  if (error) return <Alert type="error" showIcon title={error} />

  if (!view) return null

  return (
    <div className="space-y-5">
      {view.sign_confirmed_at ? (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message={`签字确认成功（${dayjs(view.sign_confirmed_at).format('YYYY-MM-DD HH:mm')}）`}
          description="本链接已失效，无需重复操作。如未领取合同原件，请联系人力资源部。"
        />
      ) : (
        <>
          <Descriptions
            size="small"
            column={1}
            bordered
            items={[
              { key: 'name', label: '姓名', children: view.name },
              { key: 'dept', label: '部门', children: view.department },
              { key: 'seq', label: '合同', children: `${view.seq_label} · ${view.term_label}` },
              {
                key: 'range',
                label: '起止日期',
                children: `${view.start_date || '-'} ~ ${view.end_date || '无固定期限'}`,
              },
              { key: 'deliver', label: '领取时间', children: view.delivered_at?.slice(0, 16) || '-' },
            ]}
          />
          <div className="text-[13px] text-gray-500">
            确认即表示您已领取上述劳动合同原件。确认结果将回传台账，作为已领取的凭证；
            链接为一次性使用，确认后自动作废。
          </div>
          <Space>
            <Button type="primary" size="large" loading={confirming} onClick={() => void confirm()}>
              点击签字
            </Button>
          </Space>
        </>
      )}
    </div>
  )
}

/** 读取 token 并选择渲染内容（必须整体包在 Suspense 内：useSearchParams 会触发 CSR bailout） */
function SignContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') || ''

  if (!token) return <Alert type="error" showIcon title="签字链接无效（缺少凭证）" />
  return <SignForm token={token} />
}

export default function ContractSignPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <Card className="w-full max-w-md" title="劳动合同签字确认">
        <Suspense fallback={<Skeleton active />}>
          <SignContent />
        </Suspense>
      </Card>
    </div>
  )
}
