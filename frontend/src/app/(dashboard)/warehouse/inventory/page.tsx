import { InventoryPanels, WarehouseOverviewCards } from '@/components/warehouse'

export default function WarehouseInventoryPage() {
  return (
    <div>
      <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">库存管理</h1>
      <p className="text-[14px] text-[var(--color-steel)] mb-4">
        现有库存、物料主数据与库位管理
      </p>
      <WarehouseOverviewCards />
      <InventoryPanels />
    </div>
  )
}
