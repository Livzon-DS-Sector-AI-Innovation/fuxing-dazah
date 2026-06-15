import { fetchNewOffboardingRecords } from '@/lib/api/hr'
import { DepartureClient } from '@/components/hr'

export default async function NewOffboardingPage() {
  const res = await fetchNewOffboardingRecords({ page: 1, page_size: 20 })

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          新厂离职管理
        </h1>
      </div>
      <DepartureClient
        initialRecords={res.data}
        initialTotal={res.meta?.total || 0}
        fetchAction={fetchNewOffboardingRecords}
      />
    </div>
  )
}
