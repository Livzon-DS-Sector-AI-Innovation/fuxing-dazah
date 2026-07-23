import { Suspense } from 'react'
import { Spin } from 'antd'
import ProbationClient from '@/components/hr/ProbationClient'

export const dynamic = 'force-dynamic'

export const metadata = { title: '试用期管理' }

export default function ProbationPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
      <ProbationClient />
    </Suspense>
  )
}
