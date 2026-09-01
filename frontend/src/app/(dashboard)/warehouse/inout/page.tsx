import { MovementTable } from '@/components/warehouse'

export default function WarehouseInoutPage() {
  return (
    <div>
      <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">出入库记录</h1>
      <p className="text-[14px] text-[var(--color-steel)] mb-4">
        登记入库/出库，撤销记录自动冲销库存
      </p>
      <MovementTable />
    </div>
  )
}
