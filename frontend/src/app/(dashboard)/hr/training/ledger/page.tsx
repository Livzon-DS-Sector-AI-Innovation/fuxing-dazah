import { Suspense } from 'react'
import { Spin } from 'antd'
import TrainingLedgerClient from '@/components/hr/TrainingLedgerClient'
import PageHeader from '@/components/hr/PageHeader'
import { fetchEmployeeByNumberAction } from '@/actions/hr'

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
      const res = await fetchEmployeeByNumberAction(employeeNumber)
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
      const res = await fetchEmployeeByNumberAction(employeeNumber)
      employeeName = res.data?.name || null
    } catch {
      employeeName = null
    }
  }

  if (!employeeNumber) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="培训台账"
          description="管理员视角 · 按部门与培训内容筛选 · 录入考核成绩 · 自动统计合格率 · 导出效果评估表"
        />
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
      <PageHeader
        title={employeeName ? `${employeeName}培训台账` : '培训台账'}
        description="员工培训教育台账记录管理"
      />

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
