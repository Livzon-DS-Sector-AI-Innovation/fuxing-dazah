import { IntelligenceCenter } from '@/components/warehouse/intelligence/IntelligenceCenter'
import { PageHeader } from '@/components/warehouse'

export default function WarehouseIntelligencePage() {
  return (
    <div>
      <PageHeader
        title="智能中心"
        description="异常检测、补货建议与效期呆滞监控"
      />
      <IntelligenceCenter />
    </div>
  )
}
