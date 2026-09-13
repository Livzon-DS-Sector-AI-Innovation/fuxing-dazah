// ── 工序流程看板（process-board）类型 ──

import type { FieldValue, EquipmentSnapshot } from './execution'

export interface ProcessBoardNode {
  id: string
  node_code: string
  name: string
  stage_name: string
  sort_order: number
}

export interface ProcessBoardPlannedItem {
  batch_id: string
  batch_no: string
  batch_status: string
  plan_order_id: string
  order_no: string
  plan_version: number
  item_id: string
  item_no: number
  planned_quantity: number | null
  unit: string | null
  planned_start: string | null
  planned_end: string | null
  item_status: string
  priority: string
  equipment_id: string | null
}

export interface ProcessBoardExecution {
  execution_id: string
  batch_id: string
  batch_no: string
  execution_seq: number
  /** 锚点执行的状态（进行中/已完成/已中止） */
  status: 'in_progress' | 'completed' | 'aborted'
  /** 看板视角状态：进行中 / 已完成待流转 / 已中止 */
  board_state: 'in_progress' | 'waiting' | 'aborted'
  owner_name: string | null
  started_at: string
  finished_at: string | null
  is_deviation: boolean
  abnormal_count: number
  batch_status: string
  batch_quantity: number | null
  batch_unit: string | null
  equipments: EquipmentSnapshot[]
  field_values: FieldValue[]
  /** 周期监控参考时长（秒）；旧数据或无可用基线时为空 */
  estimated_duration_seconds?: number | null
  /** 按监控基线计算的预计完成时间 */
  expected_finish_at?: string | null
  /** 周期监控状态：monitoring/overdue/not_monitored/sent/resolved/failed */
  timeout_monitor_status?: string | null
  /** 最近一次超时提醒发送时间 */
  timeout_notified_at?: string | null
}

export interface ProcessBoardData {
  route_id: string
  route_name: string
  route_status: string
  nodes: ProcessBoardNode[]
  planned: ProcessBoardPlannedItem[]
  columns: Record<string, ProcessBoardExecution[]>
}
