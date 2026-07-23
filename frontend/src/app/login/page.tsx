'use client'

import { useSearchParams } from 'next/navigation'
import { Button, Alert } from 'antd'
import { Suspense } from 'react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

function LoginForm() {
  const searchParams = useSearchParams()
  const error = searchParams.get('error')
  const detail = searchParams.get('detail')

  return (
    <div className="h-screen flex items-center justify-center bg-[var(--color-brand-navy)]">
      <div className="w-full max-w-md mx-4">
        <div className="bg-[var(--color-canvas)] rounded-lg p-10 shadow-lg">
          <div className="text-center mb-8">
            <h1 className="text-[22px] font-semibold mb-1">原料药工厂管理平台</h1>
            <p className="text-gray-500 text-sm">使用飞书账号安全登录</p>
          </div>
          {error && <Alert type="error" message={error} description={detail} showIcon style={{marginBottom:16}} />}
          <Button type="primary" block size="large"
            onClick={() => { window.location.href = `${API_BASE_URL}/api/v1/identity/auth/login` }}>
            飞书登录
          </Button>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return <Suspense fallback={null}><LoginForm /></Suspense>
}
