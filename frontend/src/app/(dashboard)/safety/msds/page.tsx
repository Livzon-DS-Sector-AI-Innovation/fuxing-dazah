import { Suspense } from 'react'
import MsdsPageClient from './page-client'

export const dynamic = 'force-dynamic'

export default function MsdsPage() {
  return (
    <Suspense fallback={null}>
      <MsdsPageClient />
    </Suspense>
  )
}
