import { Suspense } from 'react'
import { Spin } from 'antd'
import PositionManager from '@/components/hr/PositionManager'

export const dynamic = 'force-dynamic'
export const metadata = { title: '岗位管理' }

export default function PositionsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">岗位管理</h1>
        <p className="text-[14px] text-[var(--color-steel)]">按部门管理岗位，支持新增和删除</p>
      </div>
      <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
        <PositionManager />
      </Suspense>
    </div>
  )
}
