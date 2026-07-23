import { Suspense } from 'react'
import SystemSettingsClient from '@/components/hr/SystemSettingsClient'

export default function SettingsPage() {
  return <Suspense fallback={<div className="h-64" />}><SystemSettingsClient /></Suspense>
}
