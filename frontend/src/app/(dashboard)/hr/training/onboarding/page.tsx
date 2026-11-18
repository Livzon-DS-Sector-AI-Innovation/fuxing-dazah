import PageHeader from '@/components/hr/PageHeader'
import OnboardingPrejobClient from '@/components/hr/OnboardingPrejobClient'

export default function OnboardingTrainingPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="新员工入职培训" description="选择员工同时生成入职培训记录、岗前培训计划和员工上岗评估表，支持导出 Word、Excel 和打印" />

      <OnboardingPrejobClient />
    </div>
  )
}
