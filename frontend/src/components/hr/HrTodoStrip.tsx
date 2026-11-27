'use client'

// 人事看板顶部的「今日待办」栏（固定一条，不进可拖拽的卡片布局）：
// 离职办理、劳动合同各环节的件数，点一下直达对应环节的列表。办事员进人事模块先看这里，不用记菜单。

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { fetchLaborContractStats, fetchOffboardingCaseStats } from '@/actions/hr'
import { useHasPermission } from '@/hooks/hr'
import type { ContractTodoKey, LaborContractStats, OffboardingCaseStats, OffboardingCaseStatus } from '@/types/hr'

type DepartureStage = OffboardingCaseStatus | 'overdue'

const DEPARTURE_ITEMS: { stage: DepartureStage; label: string }[] = [
  { stage: 'draft', label: '待提交审批' },
  { stage: 'approving', label: '部门审批中' },
  { stage: 'clearing', label: '清退会签中' },
  { stage: 'cert_issuing', label: '待开具证明' },
  { stage: 'delivering', label: '待员工签收' },
  { stage: 'signed', label: '待办结' },
  { stage: 'overdue', label: '临期 / 超期' },
]

/** stats 里逐项占键的口径（不含合并口径 attention） */
type ContractStage = Exclude<ContractTodoKey, 'attention'>

const CONTRACT_ITEMS: { key: ContractStage; label: string }[] = [
  { key: 'pending_dept_approval', label: '待部门审批' },
  { key: 'to_renew', label: '待续签' },
  { key: 'to_stamp', label: '待盖章' },
  { key: 'to_deliver', label: '待领取' },
  { key: 'to_archive', label: '待归档' },
  { key: 'expired_unrenewed', label: '到期未续签' },
]

function departureCount(stats: OffboardingCaseStats | null, stage: DepartureStage): number {
  if (!stats) return 0
  return stage === 'overdue' ? stats.overdue : stats.counts[stage] || 0
}

function contractCount(stats: LaborContractStats | null, key: ContractStage): number {
  return stats?.[key] ?? 0
}

function Row({ title, to, items }: {
  title: string
  to: string
  items: { label: string; count: number; href: string }[]
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Link href={to} className="shrink-0 text-[13px] font-medium text-[var(--color-ink)] hover:underline">
        {title}
      </Link>
      <span className={`shrink-0 text-[12px] ${total > 0 ? 'text-[var(--color-warning)]' : 'text-[var(--color-steel)]'}`}>
        {total > 0 ? `${total} 件要办` : '没有要办的'}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) =>
          item.count > 0 ? (
            <Link
              key={item.label}
              href={item.href}
              className="rounded-[var(--rounded-sm)] border border-[var(--color-hairline)] bg-[var(--color-canvas)] px-2 py-0.5 text-[12px] text-[var(--color-ink)] transition-colors hover:border-[var(--color-steel)]"
            >
              {item.label} <b className="font-semibold">{item.count}</b>
            </Link>
          ) : (
            <span key={item.label} className="px-1 py-0.5 text-[12px] text-[var(--color-steel)]">
              {item.label} 0
            </span>
          ),
        )}
      </div>
    </div>
  )
}

export default function HrTodoStrip() {
  // 水合安全的权限判断：看板页在 Suspense 边界内
  const canDeparture = useHasPermission('hr:departure:read')
  const canContract = useHasPermission('hr:contract:read')
  const [departure, setDeparture] = useState<OffboardingCaseStats | null>(null)
  const [contracts, setContracts] = useState<LaborContractStats | null>(null)

  useEffect(() => {
    let cancelled = false
    // 没有相应权限（或后端 403）就不显示那一行，不影响另一行
    if (canDeparture) {
      fetchOffboardingCaseStats()
        .then((r) => { if (!cancelled) setDeparture(r.data) })
        .catch(() => {})
    }
    if (canContract) {
      fetchLaborContractStats()
        .then((r) => { if (!cancelled) setContracts(r.data) })
        .catch(() => {})
    }
    return () => { cancelled = true }
  }, [canDeparture, canContract])

  if (!canDeparture && !canContract) return null

  const departureItems = DEPARTURE_ITEMS.map((item) => ({
    label: item.label,
    count: departureCount(departure, item.stage),
    href: `/hr/departure?stage=${item.stage}`,
  }))
  const contractItems = CONTRACT_ITEMS.map((item) => ({
    label: item.label,
    count: contractCount(contracts, item.key),
    href: `/hr/labor-contracts?todo=${item.key}`,
  }))
  const nothing = !departureItems.some((i) => i.count > 0) && !contractItems.some((i) => i.count > 0)

  return (
    <section
      aria-label="今日待办"
      className="space-y-2 rounded-2xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-4"
    >
      {nothing ? (
        <div className="text-[13px] text-[var(--color-slate)]">
          离职办理和劳动合同今天都没有要办的事。
        </div>
      ) : (
        <>
          {canDeparture && <Row title="离职办理" to="/hr/departure" items={departureItems} />}
          {canContract && <Row title="劳动合同" to="/hr/labor-contracts" items={contractItems} />}
        </>
      )}
    </section>
  )
}
