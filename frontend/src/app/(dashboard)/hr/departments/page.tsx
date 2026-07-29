import { Suspense } from 'react'
import { DepartmentClient } from '@/components/hr'

export default function DepartmentsPage() {
  return <Suspense fallback={<div className="h-64" />}><DepartmentClient initialDepartments={[]} initialTotal={0} /></Suspense>
}
