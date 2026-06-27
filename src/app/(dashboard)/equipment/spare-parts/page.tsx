export const dynamic = 'force-dynamic'

import '@/lib/http-server'
import { SparePartsPage } from '@/components/equipment'
import { fetchSpareParts, fetchStockWarnings } from '@/lib/api/equipment'
import { SparePart, StockWarning } from '@/types/equipment'

export default async function SparePartsPageWrapper() {
  let spareParts: SparePart[] = []
  let sparePartTotal = 0
  let stockWarnings: StockWarning[] = []

  try {
    const result = await Promise.all([
      fetchSpareParts({ page: 1, page_size: 20 }),
      fetchStockWarnings(),
    ])
    spareParts = result[0].items
    sparePartTotal = result[0].total
    stockWarnings = result[1]
  } catch (error) {
    console.warn('备件管理数据加载失败，使用空数据:', error)
  }

  return (
    <SparePartsPage
      initialSpareParts={spareParts}
      initialSparePartTotal={sparePartTotal}
      initialStockWarnings={stockWarnings}
    />
  )
}
