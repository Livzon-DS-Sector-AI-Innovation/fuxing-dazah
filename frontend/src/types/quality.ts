// Quality 模块 TypeScript 类型

// ─── 质量标准 ───

export interface QualityStandard {
  name: string
  limit: number | null
  oot_haf: number | null
  oot_haa: number | null
  operator: string // "≤" | "≥"
}

// ─── 杂质峰面积 ───

export interface ImpurityPeakArea {
  name: string
  first: number
  second: number
}

// ─── 杂质计算结果 ───

export interface ImpurityResult {
  name: string
  first_percent: number
  second_percent: number
  limit: number | null
  oot_haf: number | null
  oot_haa: number | null
  is_pass: boolean
  is_oot: boolean
}

// ─── 主计算结果（万古霉素B、总杂质等）───

export interface CalculatedResult {
  name: string
  first_percent: number
  second_percent: number
  rounded_first: number
  rounded_second: number
  limit: number | null
  oot_haf: number | null
  oot_haa: number | null
  is_pass: boolean
  is_oot: boolean
}

// ─── 完整解析结果 ───

export interface LcReportData {
  product_name: string
  batch_number: string
  form_id: string
  standard_type: string

  // 供试液A 峰面积
  total_peak_area_a_first: number
  total_peak_area_a_second: number
  main_peak_area_a_first: number
  main_peak_area_a_second: number
  total_impurity_area_first: number
  total_impurity_area_second: number
  any_unknown_impurity_first: number
  any_unknown_impurity_second: number

  // 供试液B
  main_peak_area_b_first: number
  main_peak_area_b_second: number

  // 杂质峰面积
  impurity_peaks: ImpurityPeakArea[]

  // 计算结果
  vancomycin_b: CalculatedResult | null
  total_impurities: CalculatedResult | null
  impurity_results: ImpurityResult[]

  // 质量标准
  standards: QualityStandard[]

  // 汇总
  all_pass: boolean
  has_oot: boolean
}

// ─── 上传响应 ───

export interface UploadLcResponse {
  filename: string
  report: LcReportData
}
