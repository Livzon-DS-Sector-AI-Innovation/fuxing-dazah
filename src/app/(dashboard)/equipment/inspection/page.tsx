export const dynamic = 'force-dynamic'

import { InspectionPage } from '@/components/equipment/inspection'
import { fetchInspectionTemplates } from '@/lib/api/equipment'
import { fetchEquipments, fetchCategories } from '@/lib/api/equipment'
import type { InspectionTemplate, EquipmentCategory } from '@/types/equipment'

export default async function InspectionPageWrapper() {
  let templates: InspectionTemplate[] = []
  let equipments: { id: string; name: string; equipment_no: string }[] = []
  let categories: EquipmentCategory[] = []

  try {
    const [templatesResult, equipmentsResult, categoriesResult] = await Promise.all([
      fetchInspectionTemplates({ is_active: true, page: 1, page_size: 200 }),
      fetchEquipments({ page: 1, page_size: 200 }),
      fetchCategories(),
    ])
    templates = templatesResult.items || []
    equipments = (equipmentsResult.items || []).map(e => ({
      id: e.id,
      name: e.name,
      equipment_no: e.equipment_no,
    }))
    categories = categoriesResult || []
  } catch (error) {
    console.warn('巡检页面数据加载失败，使用空数据:', error)
  }

  return (
    <InspectionPage
      initialTemplates={templates}
      initialEquipments={equipments}
      initialCategories={categories}
    />
  )
}
