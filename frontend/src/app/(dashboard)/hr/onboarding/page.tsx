import { Suspense } from 'react'
import { OnboardingClient } from '@/components/hr'

export default function OnboardingPage() {
  return <Suspense fallback={<div className="h-64" />}><OnboardingClient initialRecords={[]} initialTotal={0} /></Suspense>
}
