import { Suspense } from 'react'
import WorkflowListPanel from '@/components/safety/WorkflowListPanel'

export default function HazardIdentificationPage() {
  return (
    <Suspense fallback={null}>
      <WorkflowListPanel />
    </Suspense>
  )
}
