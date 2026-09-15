import { InventoryPanels, WarehouseOverviewCards } from '@/components/warehouse'

export default async function WarehouseInventoryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const keyword = typeof params.keyword === 'string' ? params.keyword : undefined
  const category = typeof params.category === 'string' ? params.category : undefined

  return (
    <div>
      <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">库存管理</h1>
      <p className="text-[14px] text-[var(--color-steel)] mb-4">
        现有库存、物料主数据与库位管理
      </p>
      <WarehouseOverviewCards />
      <InventoryPanels initialKeyword={keyword} initialCategory={category} />
    </div>
  )
}
