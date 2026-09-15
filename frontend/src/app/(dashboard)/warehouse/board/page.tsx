import { TodayBoard } from '@/components/warehouse'
import { PageHeader } from '@/components/warehouse'

export default function WarehouseBoardPage() {
  return (
    <div>
      <PageHeader
        title="作业看板"
        description="今日待收、待发与已完成的出入库计划"
      />
      <TodayBoard />
    </div>
  )
}
