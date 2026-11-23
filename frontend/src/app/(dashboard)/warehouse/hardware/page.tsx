import { PageHeader } from '@/components/warehouse'
import { HardwareStockTable } from '@/components/warehouse/hardware'

export default function HardwareStockPage() {
  return (
    <div>
      <PageHeader breadcrumb={['仓储管理', '五金库']} title="五金库存" />
      <HardwareStockTable />
    </div>
  )
}
