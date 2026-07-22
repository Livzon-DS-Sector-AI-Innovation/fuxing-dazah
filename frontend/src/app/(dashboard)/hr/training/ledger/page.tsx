import { Suspense } from 'react'
import { Spin } from 'antd'
import TrainingLedgerClient from '@/components/hr/TrainingLedgerClient'
import { fetchEmployeeByNumber } from '@/lib/api/hr'

interface PageProps {
  searchParams: Promise<{
    employee_number?: string
  }>
}

export async function generateMetadata({ searchParams }: PageProps) {
  const params = await searchParams
  const employeeNumber = params.employee_number

  if (employeeNumber) {
    try {
      const res = await fetchEmployeeByNumber(employeeNumber)
      if (res.data?.name) {
        return {
          title: `${res.data.name}培训台账`,
        }
      }
    } catch {
      // fallback to default title
    }
  }

  return {
    title: '培训台账',
  }
}

export default async function TrainingLedgerPage({ searchParams }: PageProps) {
  const params = await searchParams
  const employeeNumber = params.employee_number

  let employeeName: string | null = null
  if (employeeNumber) {
    try {
      const res = await fetchEmployeeByNumber(employeeNumber)
      employeeName = res.data?.name || null
    } catch {
      employeeName = null
    }
  }

  if (!employeeNumber) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
            培训台账
          </h1>
          <p className="text-[14px] text-[var(--color-steel)]">
            员工培训教育台账记录管理 · 输入工号查看个人台账
          </p>
        </div>
        <Suspense
          fallback={
            <div className="flex items-center justify-center py-20">
              <Spin size="large" tip="加载中..." />
            </div>
          }
        >
          <TrainingLedgerClient employeeNumber="" />
        </Suspense>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          {employeeName ? `${employeeName}培训台账` : '培训台账'}
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          员工培训教育台账记录管理
        </p>
      </div>

      <Suspense
        fallback={
          <div className="flex items-center justify-center py-20">
            <Spin size="large" tip="加载中..." />
          </div>
        }
      >
        <TrainingLedgerClient employeeNumber={employeeNumber} />
      </Suspense>
    </div>
  )
}
