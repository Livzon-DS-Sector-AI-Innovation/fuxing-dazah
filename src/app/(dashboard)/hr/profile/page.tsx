import { fetchEmployees } from '@/lib/api/hr'
import EmployeeProfileClient from '@/components/hr/EmployeeProfileClient'

export default async function EmployeeProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ department?: string }>
}) {
  const params = await searchParams
  const res = await fetchEmployees({
    page: 1,
    page_size: 20,
    department: params.department,
  })

  return (
    <EmployeeProfileClient
      initialEmployees={res.data}
      initialTotal={res.meta?.total || 0}
      initialDepartment={params.department}
    />
  )
}
