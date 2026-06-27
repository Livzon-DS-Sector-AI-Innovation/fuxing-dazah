export interface Permission {
  id: string
  code: string
  name: string
  module: string
  resource: string
  action: string
  description: string | null
  is_system: boolean
}

export interface PermissionModuleGroup {
  module: string
  module_name: string
  permissions: Permission[]
}

export interface Role {
  id: string
  code: string
  name: string
  description: string | null
  data_scope: DataScope
  is_system: boolean
  created_at: string
  updated_at: string
  permission_ids: string[]
  data_scope_overrides: Record<string, DataScope>
  user_count: number
}

export type DataScope = 'all' | 'department' | 'department_and_children' | 'self_only'

export interface CreateRoleInput {
  code: string
  name: string
  description?: string
  data_scope: DataScope
  permission_ids: string[]
  data_scope_overrides?: Record<string, DataScope>
}

export interface UpdateRoleInput {
  name?: string
  description?: string
  data_scope?: DataScope
  permission_ids?: string[]
  data_scope_overrides?: Record<string, DataScope>
}

export interface UserRole {
  id: string
  user_id: string
  role_id: string
  department_id: string | null
  role_name: string
  role_code: string
}

export interface UserPermissionDetail {
  user_id: string
  user_name: string
  roles: UserRole[]
  permissions: string[]
  data_scopes: Record<string, DataScope>
}

export interface AssignRoleInput {
  role_id: string
  department_id?: string
}

export interface PersonnelItem {
  id: string
  name: string
  employee_no: string | null
  email: string | null
  mobile: string | null
  department: string | null
  position: string | null
  avatar_url: string | null
  feishu_user_id: string | null
}

export interface PersonnelListResponse {
  items: PersonnelItem[]
  total: number
  offset: number
  limit: number
}

export interface DepartmentItem {
  id: string
  feishu_department_id: string
  name: string
  member_count: number | null
}
