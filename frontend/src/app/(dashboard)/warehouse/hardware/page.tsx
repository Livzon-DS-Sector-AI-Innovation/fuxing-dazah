import { PageHeader } from '@/components/warehouse'
import { HardwareStockTable } from '@/components/warehouse/hardware'

export default function HardwareStockPage() {
  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '五金库']}
        title="五金库库存"
        description="共用类备件实时库存（可用 = 在手 − 预扣）；安全库存预警标红，点击名称看批次明细"
      />
      <HardwareStockTable />
    </div>
  )
}
