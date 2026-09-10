'use client'

import { Suspense } from 'react'
import { ContractorAdmissionPage } from '@/components/safety/contractorAdmission'

export default function ContractorAdmissionRoute() {
  return (
    <Suspense fallback={null}>
      <ContractorAdmissionPage />
    </Suspense>
  )
}
