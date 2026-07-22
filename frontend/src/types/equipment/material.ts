// ==================== 物料领用 ====================
export interface MaterialConsumeItem {
  spare_part_id: string
  quantity: number
  remark?: string
}

export interface MaterialConsumeInput {
  items: MaterialConsumeItem[]
}

export interface MaterialRecord {
  id: string
  work_order_id: string
  spare_part_id: string
  quantity: number
  remark: string | null
  created_at: string
  created_by: string | null
  spare_part_name?: string
  spare_part_code?: string
  spare_part_unit?: string
}
