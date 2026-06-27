import '@/lib/http-server'
import { EquipmentPage } from '@/components/equipment'
import { fetchCategoryTree, fetchLocationTree, fetchEquipments, fetchEquipmentStatistics, fetchDepartments } from '@/lib/api/equipment'
import type { DepartmentOption } from '@/lib/api/equipment'
import { EquipmentCategory, Location, Equipment, EquipmentStatistics } from '@/types/equipment'

// 强制动态渲染：不在构建时预渲染，每次请求都实时从后端获取数据
export const dynamic = 'force-dynamic'

// 默认空数据
const defaultStatistics: EquipmentStatistics = {
  total: 0,
  by_status: {} as Record<string, number>,
  by_category: {} as Record<string, number>,
  by_location: {} as Record<string, number>,
}

export default async function EquipmentPageWrapper() {
  let categories: EquipmentCategory[] = []
  let locations: Location[] = []
  let equipments: Equipment[] = []
  let total = 0
  let statistics = defaultStatistics
  let departments: DepartmentOption[] = []

  // Promise.allSettled：并行请求 + 独立容错，避免一个失败拖垮全部数据
  const results = await Promise.allSettled([
    fetchCategoryTree(),
    fetchLocationTree(),
    fetchEquipments({ page: 1, page_size: 20 }),
    fetchEquipmentStatistics(),
    fetchDepartments(),
  ])

  if (results[0].status === 'fulfilled') {
    categories = results[0].value
  } else {
    console.warn('加载分类树失败:', results[0].reason)
  }
  if (results[1].status === 'fulfilled') {
    locations = results[1].value
  } else {
    console.warn('加载位置树失败:', results[1].reason)
  }
  if (results[2].status === 'fulfilled') {
    equipments = results[2].value.items
    total = results[2].value.total
  } else {
    console.warn('加载设备列表失败:', results[2].reason)
  }
  if (results[3].status === 'fulfilled') {
    statistics = results[3].value
  } else {
    console.warn('加载设备统计失败:', results[3].reason)
  }
  if (results[4].status === 'fulfilled') {
    departments = results[4].value
  } else {
    console.warn('加载部门列表失败:', results[4].reason)
  }

  return (
    <EquipmentPage
      initialCategories={categories}
      initialLocations={locations}
      initialEquipments={equipments}
      initialTotal={total}
      initialStatistics={statistics}
      initialDepartments={departments}
    />
  )
}
