import { Suspense } from 'react'
import SystemSettingsClient from '@/components/hr/SystemSettingsClient'
import UserDeptAccessClient from '@/components/hr/UserDeptAccessClient'
import { ReminderSettingsCard } from '@/components/hr'

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <div className="space-y-6">
        <ReminderSettingsCard />
        <SystemSettingsClient />
        <UserDeptAccessClient />
      </div>
    </Suspense>
  )
}
