// 巡检分析类型
export interface TrendDataPoint {
  date: string
  value: number | null
  result: string
}

export interface TrendSeries {
  template_item_id: string
  item_name: string
  unit: string
  data_points: TrendDataPoint[]
}

export interface TrendResponse {
  equipment_name: string
  equipment_no: string
  series: TrendSeries[]
}

export interface TrendQuery {
  equipment_id: string
  item_ids: string[]
  from_date?: string
  to_date?: string
}

export interface AnomalyRankingItem {
  equipment_id?: string | null
  equipment_name?: string
  equipment_no?: string
  template_item_id?: string | null
  item_name?: string
  template_name?: string
  total_count: number
  abnormal_count: number
  anomaly_rate: number
}

export interface AnomalyMonthlyItem {
  month: string
  normal: number
  abnormal: number
  skip: number
  total: number
}

export interface AnomalyMatrixCell {
  equipment_id: string
  equipment_name: string
  equipment_no: string
  template_item_id: string
  item_name: string
  total_count: number
  abnormal_count: number
  anomaly_rate: number
}

export interface AnomalyResponse {
  equipment_ranking: AnomalyRankingItem[]
  item_ranking: AnomalyRankingItem[]
  monthly_trend: AnomalyMonthlyItem[]
  matrix: AnomalyMatrixCell[]
}

export interface AnomalyQuery {
  from_date?: string
  to_date?: string
}

export interface EquipmentListItem {
  equipment_id: string
  equipment_name: string
  equipment_no: string
  numeric_item_count: number
  latest_inspection_date: string
}

export interface EquipmentListResponse {
  equipments: EquipmentListItem[]
}

export interface LinkagePoint {
  month: string
  series: string
  count: number
}

export interface LinkageResponse {
  points: LinkagePoint[]
}

export interface LinkageQuery {
  from_date?: string
  to_date?: string
}
