import { Suspense } from 'react'
import TrainingNotificationClient from '@/components/hr/TrainingNotificationClient'

export default function TrainingNotificationPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          培训通知
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          填写培训信息，自动生成培训通知 Word 文档
        </p>
      </div>

      <Suspense fallback={<div>加载中...</div>}>
        <TrainingNotificationClient />
      </Suspense>
    </div>
  )
}
