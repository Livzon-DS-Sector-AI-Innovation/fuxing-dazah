import { Suspense } from 'react'
import { Spin } from 'antd'
import { PositionManager } from '@/components/hr/positions'

export const dynamic = 'force-dynamic'
export const metadata = { title: '岗位管理' }

export default function PositionsPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
      <PositionManager />
    </Suspense>
  )
}
