// QA COA 域类型，对应后端 app/modules/qa/{models,schemas}/coa（/api/v1/qa/coa）。

export type CoaValueType = 'number' | 'text'
export type CoaSourceType = 'manual' | 'import'

export interface CoaProduct {
  id: string
  code: string
  name: string
  name_en: string | null
  is_active: boolean
  sort_order: number
  remark: string | null
  /** 列表接口额外返回：该产品下客户标准数。 */
  standard_count?: number
}

/** docx 解析出的建品建议（短码/中英文品名，可能为 null）。 */
export interface CoaProductDraft {
  code: string | null
  name: string | null
  name_en: string | null
}

export interface CoaStandardItem {
  id: string
  standard_id: string
  code: string
  group_name: string | null
  name_cn: string
  name_en: string | null
  value_type: CoaValueType
  unit: string | null
  spec_text: string | null
  spec_min: number | null
  spec_max: number | null
  sort_order: number
  is_active: boolean
  remark: string | null
}

/** 项目入参：id 为空=新建；替换场景带 id=保留更新（值引用不断）。 */
export interface CoaItemInput {
  id?: string | null
  code?: string | null
  group_name?: string | null
  name_cn: string
  name_en?: string | null
  value_type: CoaValueType
  unit?: string | null
  spec_text?: string | null
  spec_min?: number | null
  spec_max?: number | null
  sort_order?: number | null
  is_active?: boolean
  remark?: string | null
}

/** 导入确认时并入标准的新项目（携带首份结果值）。 */
export interface CoaNewItemInput extends CoaItemInput {
  value_num?: number | null
  value_text?: string | null
}

export interface CoaStandard {
  id: string
  product_id: string
  code: string
  name: string
  customer: string | null
  market: string | null
  version: string | null
  is_active: boolean
  source: CoaSourceType
  remark: string | null
  item_count?: number
  report_count?: number
  items?: CoaStandardItem[]
}

export interface CoaStandardInput {
  product_id: string
  code: string
  name: string
  customer?: string | null
  market?: string | null
  version?: string | null
  is_active?: boolean
  remark?: string | null
  items?: CoaItemInput[]
  /** docx 导入草稿的原始提取结果（source=import 留底）。 */
  raw_extract?: Record<string, unknown> | null
}

export interface CoaProductInput {
  code: string
  name: string
  name_en?: string | null
  is_active?: boolean
  sort_order?: number
  remark?: string | null
}

export interface CoaValue {
  item_id: string
  value_num: number | null
  value_text: string | null
  remark: string | null
}

export interface CoaValueInput {
  item_id: string
  value_num?: number | null
  value_text?: string | null
  remark?: string | null
}

export interface CoaReport {
  id: string
  product_id: string
  standard_id: string
  report_no: string
  serial_no: string | null
  batch_no: string
  mfg_date: string | null
  exp_date: string | null
  issued_date: string | null
  packaging: string | null
  batch_size: string | null
  storage: string | null
  conclusion: string | null
  source: CoaSourceType
  remark: string | null
  values?: CoaValue[]
  /** 矩阵接口返回：item_id → 值。 */
  value_map?: Record<string, { num: number | null; text: string | null }>
  /** 矩阵接口返回：归属标准短码。 */
  standard_code?: string | null
}

export interface CoaReportInput {
  product_id: string
  standard_id: string
  report_no: string
  batch_no: string
  serial_no?: string | null
  mfg_date?: string | null
  exp_date?: string | null
  issued_date?: string | null
  packaging?: string | null
  batch_size?: string | null
  storage?: string | null
  conclusion?: string | null
  remark?: string | null
  values?: CoaValueInput[]
  new_items?: CoaNewItemInput[]
  raw_extract?: Record<string, unknown> | null
}

// ─────────────────────── docx 导入预览 ───────────────────────

export interface CoaStandardImportPreview {
  product: CoaProduct | null
  product_draft: CoaProductDraft
  standard_draft: {
    code: string | null
    name: string
    customer: string | null
    market: string | null
    version: string | null
    items: CoaItemInput[]
  }
  raw_extract: Record<string, unknown>
}

export interface CoaReportImportPreview {
  product: CoaProduct | null
  product_draft: CoaProductDraft
  standard: CoaStandard | null
  /** 自动匹配失败时的候选（前端让用户手选后带 standard_id 重预览）。 */
  standard_candidates: CoaStandard[]
  report_draft: {
    report_no: string | null
    serial_no: string | null
    batch_no: string | null
    mfg_date: string | null
    exp_date: string | null
    issued_date: string | null
    packaging: string | null
    batch_size: string | null
    storage: string | null
    conclusion: string | null
  }
  matched_items: {
    item_id: string
    name: string
    spec_text: string | null
    value_num: number | null
    value_text: string | null
  }[]
  /** docx 有、标准无 → 可勾选并入标准（携带值）。 */
  unmatched_items: (CoaItemInput & {
    value_num: number | null
    value_text: string | null
  })[]
  /** 标准有、docx 无（提示留空/补录）。 */
  missing_items: CoaStandardItem[]
  raw_extract: Record<string, unknown>
}

/** 出具登记矩阵：列=各标准 active 项目（两级列头），行=报告。 */
/** 矩阵合并列：跨标准同名（同 code）项目共用一列；item_ids 供按报告值回填。 */
export interface CoaMatrixColumn {
  code: string
  name_cn: string
  item_ids: string[]
  /** 去重后的非空规格（不同标准规格不同时并列提示） */
  spec_texts: string[]
}

export interface CoaMatrix {
  product: CoaProduct
  columns: CoaMatrixColumn[]
  /** 各标准及其项目（登记弹窗选标准/逐项填值用）；矩阵列以 columns 为准 */
  standards: (CoaStandard & { items: CoaStandardItem[] })[]
  rows: CoaReport[]
}
