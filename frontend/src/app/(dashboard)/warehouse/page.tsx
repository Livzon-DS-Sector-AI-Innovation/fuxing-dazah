import { WarehouseDashboard } from '@/components/warehouse'

// V2.0 分期A：仓储首页从"跳转库存页"升级为驾驶舱
export default function WarehousePage() {
  return (
    <div>
      <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">仓储驾驶舱</h1>
      <p className="text-[14px] text-[var(--color-steel)] mb-4">
        库存总览、出入库趋势、分布与待办
      </p>
      <WarehouseDashboard />
    </div>
  )
}
