import DailyRiskReportPanel from '@/components/safety/DailyRiskReportPanel'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '关键风险作业报备 - DAZAH',
}

export default function RiskReportingPage() {
  return (
    <div className="p-6">
      <div className="mb-4">
        <h2 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
          关键风险作业报备
        </h2>
        <p style={{ fontSize: 14, color: '#787671', margin: '4px 0 0' }}>
          每日风险作业报备审批管理
        </p>
      </div>

      <DailyRiskReportPanel />
    </div>
  )
}
