import { fetchNewDepartments } from '@/lib/api/hr'
import { DepartmentClient } from '@/components/hr'

export default async function NewDepartmentsPage() {
  const res = await fetchNewDepartments({ page: 1, page_size: 100 })

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          新厂部门管理
        </h1>
      </div>
      <DepartmentClient
        initialDepartments={res.data}
        initialTotal={res.meta?.total || 0}
        fetchAction={fetchNewDepartments}
      />
    </div>
  )
}
