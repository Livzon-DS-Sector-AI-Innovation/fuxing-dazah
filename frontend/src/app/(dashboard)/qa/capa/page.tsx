import { Suspense } from 'react'
import { CapaLedgerPage } from '@/components/qa'

export const dynamic = 'force-dynamic'

export default function QaCapaPage() {
  // CapaLedgerPage 读取 ?id= 打开详情，useSearchParams 需要 Suspense 边界。
  return (
    <Suspense fallback={null}>
      <CapaLedgerPage />
    </Suspense>
  )
}
