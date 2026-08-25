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

/** 字段趋势点（跨批次时间序列） */
export interface FieldTrendPoint {
  batch_no: string
  filled_at: string
  value: number
}

/** 工段汇总平铺矩阵列定义（工序字段或计算字段） */
export interface StageSummaryColumn {
  /** 工序节点 id，前端按节点分组表头 */
  node_id: string
  node_code: string
  node_name: string
  field_key: string
  field_label: string
  unit: string | null
  kind: 'field' | 'computed'
  /** 行列扁平字典的键：{node_id}.{field_key}（node_code 仅路线内唯一，多路线会撞键） */
  col_key: string
}

/** 工段汇总平铺矩阵行：单批次一行，values/computed 键为 {node_id}.{field_key} */
export interface StageSummaryRow {
  batch_id: string
  batch_no: string
  values: Record<string, number | string | boolean | null>
  computed: Record<string, number | null>
}

/** 工段汇总平铺矩阵响应 */
export interface StageSummary {
  columns: StageSummaryColumn[]
  rows: StageSummaryRow[]
}
