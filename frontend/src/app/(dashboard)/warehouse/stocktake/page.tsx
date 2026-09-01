import { StocktakeBoard } from '@/components/warehouse'

export default function WarehouseStocktakePage() {
  return (
    <div>
      <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">库存盘点</h1>
      <p className="text-[14px] text-[var(--color-steel)] mb-4">
        按库存快照创建盘点单，确认后按实盘结果自动调整库存
      </p>
      <StocktakeBoard />
    </div>
  )
}
