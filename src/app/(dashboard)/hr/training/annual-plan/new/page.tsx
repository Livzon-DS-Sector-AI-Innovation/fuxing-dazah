import AnnualPlanForm from '@/components/hr/AnnualPlanForm'

export const metadata = {
  title: '新建年度培训计划',
}

export default function NewAnnualPlanPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          新建年度培训计划
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          选择部门并创建新的年度培训计划
        </p>
      </div>

      <AnnualPlanForm />
    </div>
  )
}
