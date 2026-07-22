import OnboardingPrejobClient from '@/components/hr/OnboardingPrejobClient'

export default function OnboardingTrainingPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          新员工入职培训
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          选择员工同时生成入职培训记录、岗前培训计划和员工上岗评估表，支持导出 Word、Excel 和打印
        </p>
      </div>

      <OnboardingPrejobClient />
    </div>
  )
}
