import { ReportCenter } from '@/components/warehouse/reports/ReportCenter'
import { PageHeader } from '@/components/warehouse'

export default function WarehouseReportsPage() {
  return (
    <div>
      <PageHeader title="报表中心" description="出入库月报、自然语言导出" />
      <ReportCenter />
    </div>
  )
}
