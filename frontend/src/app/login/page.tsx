'use client'

import { useSearchParams } from 'next/navigation'
import { Button, Alert } from 'antd'
import { Suspense } from 'react'
import LightPillar from '@/components/LightPillar'
import SpotlightCard from '@/components/SpotlightCard'
import { AntdProvider } from '@/components/AntdProvider'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL

function LoginForm() {
  const searchParams = useSearchParams()
  const error = searchParams.get('error')
  const detail = searchParams.get('detail')

  const handleLogin = () => {
    window.location.href = `${API_BASE_URL}/api/v1/identity/auth/login`
  }

  return (
    <div className="relative h-screen flex items-center justify-center overflow-hidden bg-[var(--color-brand-navy-deep)]">
      {/* Light Pillar 背景，色彩取 DESIGN.md 品牌紫/粉 */}
      <LightPillar
        topColor="#7b3ff2"
        bottomColor="#ff64c8"
        className="pointer-events-none"
        pillarWidth={8}
        pillarRotation={30}
        quality="medium"
        noiseIntensity={0}
        mixBlendMode="screen"
      />
      <div className="relative z-10 w-full max-w-md mx-4">
        <SpotlightCard
          spotlightColor="rgba(255, 255, 255, 0.5)"
          className="bg-white/25 backdrop-blur-md border border-white/40 rounded-[var(--rounded-lg)] p-10 shadow-[rgba(15,15,15,0.2)_0px_24px_48px_-8px]"
        >
          {/* Logo & Title */}
          <div className="text-center mb-8">
            <div className="w-12 h-12 rounded-[var(--rounded-md)] bg-[var(--color-primary)] flex items-center justify-center mx-auto mb-4">
              <span className="text-white text-lg font-semibold">API</span>
            </div>
            <h1 className="text-[var(--color-on-dark)] text-[22px] font-semibold leading-[1.3] mb-1">
              原料药工厂管理平台
            </h1>
            <p className="text-white/70 text-[14px] leading-[1.5]">
              使用飞书账号安全登录
            </p>
          </div>

          {/* Error Display */}
          {error && (
            <Alert
              type="error"
              title="登录失败"
              description={
                <div>
                  <p><strong>错误类型：</strong>{error}</p>
                  {detail && <p style={{ marginTop: 4, wordBreak: 'break-all' }}><strong>详情：</strong>{decodeURIComponent(detail)}</p>}
                </div>
              }
              showIcon
              closable
              style={{ marginBottom: 16 }}
            />
          )}

          {/* Login Button */}
          <Button
            type="primary"
            block
            size="large"
            onClick={handleLogin}
            className="h-[44px] text-[14px] font-medium"
          >
            飞书登录
          </Button>
        </SpotlightCard>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <AntdProvider>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </AntdProvider>
  )
}
