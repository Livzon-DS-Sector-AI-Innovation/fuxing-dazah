import { fetchOffboardingRecords } from '@/lib/api/hr'
import { OffboardingClient } from '@/components/hr'

export default async function OffboardingPage() {
  const res = await fetchOffboardingRecords({ page: 1, page_size: 20 })

  return (
    <OffboardingClient
      initialRecords={res.data}
      initialTotal={res.meta?.total || 0}
    />
  )
}
