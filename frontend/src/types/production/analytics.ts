/** 单工序周期统计 */
export interface StepCycleStat {
  node_id: string
  node_name: string
  stage_name: string
  sort_order: number
  /** 样本数 */
  n: number
  /** 平均耗时（小时） */
  avg_hours: number
  /** 最短耗时（小时） */
  min_hours: number | null
  /** 最长耗时（小时） */
  max_hours: number | null
}

/** 工序周期分析响应 */
export interface StepCycleResponse {
  steps: StepCycleStat[]
  total_batches: number
  sample_note: string | null
}
