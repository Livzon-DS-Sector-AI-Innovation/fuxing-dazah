// ==================== 故障代码 ====================
export type FailureCodeType = 'symptom' | 'cause' | 'action'

export interface FailureCode {
  id: string
  code: string
  name: string
  description: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
}

export interface CreateFailureCodeInput {
  code: string
  name: string
  description?: string
  sort_order?: number
  is_active?: boolean
}

export interface UpdateFailureCodeInput {
  code?: string
  name?: string
  description?: string
  sort_order?: number
  is_active?: boolean
}
