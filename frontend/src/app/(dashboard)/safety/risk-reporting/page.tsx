import KeyRiskOpsManagement from '@/components/safety/KeyRiskOpsManagement'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '关键风险作业管理 - DAZAH',
}

export default function RiskReportingPage() {
  return <KeyRiskOpsManagement />
}
