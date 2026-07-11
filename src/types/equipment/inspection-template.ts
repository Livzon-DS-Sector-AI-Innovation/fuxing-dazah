// ==================== 巡检模板 ====================
export interface InspectionTemplate {
  id: string
  name: string
  description: string | null
  equipment_category_id: string | null
  is_active: boolean
  items_count: number
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_category_name?: string
  items?: InspectionTemplateItem[]
}

export interface InspectionTemplateItem {
  id: string
  template_id: string
  item_name: string
  item_description: string | null
  expected_result: string | null
  check_method: string | null
  data_type: string
  unit: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CreateInspectionTemplateInput {
  name: string
  description?: string
  equipment_category_id?: string
  is_active?: boolean
  items?: CreateInspectionTemplateItemInput[]
}

export interface UpdateInspectionTemplateInput {
  name?: string
  description?: string
  equipment_category_id?: string
  is_active?: boolean
}

export interface CreateInspectionTemplateItemInput {
  item_name: string
  item_description?: string
  expected_result?: string
  check_method?: string
  data_type?: string
  unit?: string
  sort_order?: number
}

export interface UpdateInspectionTemplateItemInput {
  item_name?: string
  item_description?: string
  expected_result?: string
  check_method?: string
  data_type?: string
  unit?: string
  sort_order?: number
}

export interface InspectionTemplateFilters {
  equipment_category_id?: string
  is_active?: boolean
  keyword?: string
  page?: number
  page_size?: number
}

export interface InspectionTemplateListResponse {
  items: InspectionTemplate[]
  total: number
  page: number
  page_size: number
}

export interface InspectionRecordItem {
  item_id: string
  result: string
  actual_value?: string
  remark?: string
}

export interface InspectionCompleteInput {
  records: InspectionRecordItem[]
}
