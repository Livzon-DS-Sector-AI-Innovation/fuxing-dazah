export const dynamic = 'force-dynamic'

import '@/lib/http-server'
import { SparePartsPage } from '@/components/equipment'
import { fetchSpareParts, fetchStockWarnings } from '@/lib/api/equipment'
import { SparePart, StockWarning } from '@/types/equipment'
import { getCurrentUser } from '@/actions/auth'

export default async function SparePartsPageWrapper() {
  let spareParts: SparePart[] = []
  let sparePartTotal = 0
  let stockWarnings: StockWarning[] = []
  let userDepartmentName: string | null = null

  try {
    const result = await Promise.all([
      fetchSpareParts({ page: 1, page_size: 20 }),
      fetchStockWarnings(),
      getCurrentUser(),
    ])
    spareParts = result[0].items
    sparePartTotal = result[0].total
    stockWarnings = result[1]
    userDepartmentName = result[2]?.department ?? null
  } catch (error) {
    console.warn('备件管理数据加载失败，使用空数据:', error)
  }

  return (
    <SparePartsPage
      initialSpareParts={spareParts}
      initialSparePartTotal={sparePartTotal}
      initialStockWarnings={stockWarnings}
      userDepartmentName={userDepartmentName}
    />
  )
}
