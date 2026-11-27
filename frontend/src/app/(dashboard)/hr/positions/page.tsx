import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Spin } from 'antd'
import PositionManager from '@/components/hr/PositionManager'

export const dynamic = 'force-dynamic'
export const metadata = { title: '岗位管理' }

export default function PositionsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="岗位管理" description="按部门管理岗位，支持新增和删除" />
      <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
        <PositionManager />
      </Suspense>
    </div>
  )
}
