import { Suspense } from 'react'
import SystemSettingsClient from '@/components/hr/SystemSettingsClient'
import UserDeptAccessClient from '@/components/hr/UserDeptAccessClient'

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <div className="space-y-6">
        <SystemSettingsClient />
        <UserDeptAccessClient />
      </div>
    </Suspense>
  )
}
