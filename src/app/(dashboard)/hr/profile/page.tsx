import { fetchEmployees } from '@/lib/api/hr'
import EmployeeProfileClient from '@/components/hr/EmployeeProfileClient'

export default async function EmployeeProfilePage() {
  const res = await fetchEmployees({ page: 1, page_size: 20 })

  return (
    <EmployeeProfileClient
      initialEmployees={res.data}
      initialTotal={res.meta?.total || 0}
    />
  )
}
