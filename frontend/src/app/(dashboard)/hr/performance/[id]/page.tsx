import PerformanceFormClient from '@/components/hr/PerformanceFormClient'

export default function PerformanceDetailPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">绩效考核详情</h1>
        <p className="text-[14px] text-[var(--color-steel)]">编辑自评与领导评分</p>
      </div>
      <PerformanceFormClient />
    </div>
  )
}
