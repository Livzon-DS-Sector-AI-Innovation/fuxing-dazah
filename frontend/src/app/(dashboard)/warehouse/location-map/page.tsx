import { LocationMap } from '@/components/warehouse/LocationMap'
import { PageHeader } from '@/components/warehouse'

export default function WarehouseLocationMapPage() {
  return (
    <div>
      <PageHeader title="库位地图" description="按库区/巷道可视化查看占用情况" />
      <LocationMap />
    </div>
  )
}
