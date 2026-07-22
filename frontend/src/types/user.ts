export interface User {
  id: string
  name: string
  email: string | null
  mobile: string | null
  avatar_url: string | null
  employee_no: string | null
  department: string | null
  position: string | null
  // 新增权限相关字段（/me 接口返回）
  permissions?: string[]
  roles?: string[]
  data_scopes?: Record<string, string>
}

export interface ImpersonateUserInfo {
  id: string
  name: string
  department: string
  position: string
}

export interface ImpersonationStatus {
  is_impersonating: boolean
  real_user: ImpersonateUserInfo | null
  target_user: ImpersonateUserInfo | null
  expires_at: string | null
}
