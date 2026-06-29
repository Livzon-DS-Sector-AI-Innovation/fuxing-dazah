// safety module TypeScript types

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  meta?: {
    page?: number
    page_size?: number
    total?: number
  }
}

export interface SafetyDashboardStats {
  total_checks: number
  pending_checks: number
  open_hazards: number
  overdue_hazards: number
  recent_accidents: number
  upcoming_trainings: number
}

