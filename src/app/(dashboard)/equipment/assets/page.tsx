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

  // 每个 API 独立 try/catch，避免一个失败拖垮全部数据
  try {
    categories = await fetchCategoryTree()
  } catch (error) {
    console.warn('加载分类树失败:', error)
  }
  try {
    locations = await fetchLocationTree()
  } catch (error) {
    console.warn('加载位置树失败:', error)
  }
  try {
    const result = await fetchEquipments({ page: 1, page_size: 20 })
    equipments = result.items
    total = result.total
  } catch (error) {
    console.warn('加载设备列表失败:', error)
  }
  try {
    statistics = await fetchEquipmentStatistics()
  } catch (error) {
    console.warn('加载设备统计失败:', error)
  }
  try {
    departments = await fetchDepartments()
  } catch (error) {
    console.warn('加载部门列表失败:', error)
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
