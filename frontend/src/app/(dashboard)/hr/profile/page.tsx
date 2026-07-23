import { Suspense } from 'react'
import EmployeeProfileClient from '@/components/hr/EmployeeProfileClient'

export default function EmployeeProfilePage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <EmployeeProfileClient initialEmployees={[]} initialTotal={0} />
    </Suspense>
  )
}
