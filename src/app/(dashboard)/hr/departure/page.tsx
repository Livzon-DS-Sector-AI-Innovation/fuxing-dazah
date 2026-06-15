import { fetchDepartureRecords } from '@/lib/api/hr'
import { DepartureClient } from '@/components/hr'

export default async function DeparturePage() {
  const res = await fetchDepartureRecords({ page: 1, page_size: 20 })

  return (
    <DepartureClient
      initialRecords={res.data}
      initialTotal={res.meta?.total || 0}
    />
  )
}
