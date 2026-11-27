import { Suspense } from 'react'
import { AprEntryPage } from '@/components/qa'

export const dynamic = 'force-dynamic'

export default function QaAprEntryPage() {
  // AprEntryPage 读写 ?product=&section=&year= 等查询串，useSearchParams 需要 Suspense 边界
  //（现在靠 force-dynamic 侥幸通过，去掉该行就会构建报错）。
  return (
    <Suspense fallback={null}>
      <AprEntryPage />
    </Suspense>
  )
}
