import { fetchOnboardingRecords } from '@/lib/api/hr'
import { OnboardingClient } from '@/components/hr'

export default async function OnboardingPage() {
  const res = await fetchOnboardingRecords({ page: 1, page_size: 20 })

  return (
    <OnboardingClient
      initialRecords={res.data}
      initialTotal={res.meta?.total || 0}
    />
  )
}
