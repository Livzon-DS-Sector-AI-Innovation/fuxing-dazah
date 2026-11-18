import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Spin } from 'antd'
import TrainingNotificationClient from '@/components/hr/TrainingNotificationClient'

export default function TrainingNotificationPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="培训通知" description="填写培训信息，自动生成培训通知 Word 文档" />

      <Suspense fallback={<div className="flex justify-center py-20"><Spin size="large" /></div>}>
        <TrainingNotificationClient />
      </Suspense>
    </div>
  )
}
