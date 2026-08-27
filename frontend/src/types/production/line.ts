// 产线字典与用户-产线绑定 TypeScript 类型

export interface Line {
  id: string
  name: string
  remark: string | null
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export interface LineCreateInput {
  name: string
  remark?: string
}

export interface LineUpdateInput {
  name?: string
  remark?: string | null
}

export interface LineAssignment {
  id: string
  user_id: string
  line_id: string
  line_name?: string | null
  created_at: string
}

export interface LineAssignmentCreateInput {
  user_id: string
  line_id: string
}

export interface LineProductLink {
  id: string
  line_id: string
  product_id: string
  line_name?: string | null
  product_name?: string | null
  created_at: string
}

export interface LineProductLinkCreateInput {
  line_id: string
  product_id: string
}
