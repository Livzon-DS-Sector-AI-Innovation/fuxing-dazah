import { ReconciliationCenter } from '@/components/warehouse/ReconciliationCenter'
import { PageHeader } from '@/components/warehouse'

export default function WarehouseReconciliationPage() {
  return (
    <div>
      <PageHeader
        title="对账中心"
        description="本地库存与飞书台账一致性核查"
      />
      <ReconciliationCenter />
    </div>
  )
}
