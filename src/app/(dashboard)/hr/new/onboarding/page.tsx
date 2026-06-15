import { fetchNewOnboardingRecords } from '@/lib/api/hr'
import { OnboardingClient } from '@/components/hr'

export default async function NewOnboardingPage() {
  const res = await fetchNewOnboardingRecords({ page: 1, page_size: 20 })

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          新厂入职台账
        </h1>
      </div>
      <OnboardingClient
        initialRecords={res.data}
        initialTotal={res.meta?.total || 0}
        fetchAction={fetchNewOnboardingRecords}
      />
    </div>
  )
}
