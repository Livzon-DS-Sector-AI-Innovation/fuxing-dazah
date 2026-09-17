import { InventoryPanels, PageHeader, WarehouseOverviewCards } from '@/components/warehouse'

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
      <PageHeader
        breadcrumb={['仓储管理', '库存管理']}
        title="库存管理"
        description="现有库存、物料主数据与库位管理"
      />
      <WarehouseOverviewCards />
      <InventoryPanels initialKeyword={keyword} initialCategory={category} />
    </div>
  )
}
