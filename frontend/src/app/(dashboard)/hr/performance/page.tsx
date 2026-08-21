import PerformanceListClient from '@/components/hr/PerformanceListClient'

export default function PerformancePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">月度绩效考核</h1>
        <p className="text-[14px] text-[var(--color-steel)]">部门负责人自评与分管领导评分</p>
      </div>
      <PerformanceListClient />
    </div>
  )
}
