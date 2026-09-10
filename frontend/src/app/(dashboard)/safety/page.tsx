import {
  getHazards,
  getHazardIdentifications,
  getExpiringCertificates,
  getSpecialOperationReports,
  getKeyRiskOperationReports,
} from '@/actions/safety'
import { SafetyDashboard } from '@/components/safety'
import type { SpecialOperationReport, KeyRiskOperationReport, TrainingRecord } from '@/types/safety'

export const dynamic = 'force-dynamic'
export const revalidate = 60

function isToday(dateStr?: string): boolean {
  if (!dateStr) return false
  const today = new Date()
  const d = new Date(dateStr)
  return (
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  )
}

async function fetchDashboardData() {
  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`

  const [
    hazardsRes,
    identificationsRes,
    expiringCertsRes,
    specialOpReportsRes,
    keyRiskOpsRes,
  ] = await Promise.all([
    getHazards({ page_size: 200 }),
    getHazardIdentifications({ page_size: 200 }),
    getExpiringCertificates().catch(() => ({ data: [] })),
    getSpecialOperationReports({ page_size: 50 }).catch(() => ({ data: [], meta: { total: 0 } })),
    getKeyRiskOperationReports({ page_size: 50, date_from: todayStr, date_to: todayStr, apply_status: '已通过' }).catch(() => ({ data: [], meta: { total: 0 } })),
  ])

  // 未关闭隐患：过滤 status != closed && != verified
  const hazardsAll = Array.isArray((hazardsRes as { data?: unknown[] }).data)
    ? (hazardsRes as { data: { status: string }[] }).data
    : []
  const openHazardCount = hazardsAll.filter(
    (h) => h.status !== 'closed' && h.status !== 'verified'
  ).length

  // 未完成危险源辨识：过滤 overall_status = draft 或 in_progress
  const identificationsAll = Array.isArray((identificationsRes as { data?: unknown[] }).data)
    ? (identificationsRes as { data: { overall_status: string }[] }).data
    : []
  const unfinishedIdentCount = identificationsAll.filter(
    (i) => i.overall_status === 'draft' || i.overall_status === 'in_progress'
  ).length

  // 即将到期证书
  const expiringCerts = (Array.isArray(expiringCertsRes?.data) ? expiringCertsRes.data : []) as TrainingRecord[]

  // 当天特殊作业报备
  const specialOpReports = (Array.isArray((specialOpReportsRes as { data?: SpecialOperationReport[] }).data)
    ? (specialOpReportsRes as { data: SpecialOperationReport[] }).data
    : []) as SpecialOperationReport[]
  const todaySpecialOps = specialOpReports.filter((r) => isToday(r.planned_start_time))

  // 当天关键风险作业（Bitable 同步，已通过）
  const keyRiskOps = (Array.isArray((keyRiskOpsRes as { data?: KeyRiskOperationReport[] }).data)
    ? (keyRiskOpsRes as { data: KeyRiskOperationReport[] }).data
    : []) as KeyRiskOperationReport[]

  return {
    openHazardCount,
    unfinishedIdentCount,
    expiringCerts,
    todaySpecialOps,
    todayDailyRisks: keyRiskOps,
  }
}

export default async function SafetyPage() {
  const data = await fetchDashboardData()

  return <SafetyDashboard data={data} />
}
