// 设备状态日志与时间开动率类型

import type { EquipmentStatus, RunningStatus } from './equipment'

export type StatusLogSource = 'init' | 'create' | 'manual' | 'work_order' | 'import'

export interface EquipmentStatusLog {
  id: string
  log_type: 'status' | 'running'
  old_status: EquipmentStatus | RunningStatus | null
  new_status: EquipmentStatus | RunningStatus
  changed_at: string // ISO datetime
  source: StatusLogSource
}

export interface AvailabilityItem {
  equipment_id: string
  equipment_no: string
  name: string
  current_status: EquipmentStatus
  current_running_status: RunningStatus
  status_hours: Partial<Record<RunningStatus, number>>
  available_hours: number
  total_hours: number
  availability_rate: number | null
}

export interface AvailabilityResponse {
  from_date: string
  to_date: string
  overall_rate: number | null
  items: AvailabilityItem[]
}
