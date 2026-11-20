// QA COA 域类型，对应后端 app/modules/qa/{models,schemas}/coa（/api/v1/qa/coa）。

export type CoaValueType = 'number' | 'text'
export type CoaSourceType = 'manual' | 'import'
export type CoaFieldType = 'text' | 'date'

/** 批次信息字段配置行：产品默认（product_id）或标准覆盖（standard_id，详情生效集不带归属键）。 */
export interface CoaProductField {
  id: string | null
  product_id?: string
  standard_id?: string
  /** 字段键（产品/标准内唯一，报告导入按配置提取的锚点），如 retest_date */
  key: string
  label_cn: string
  label_en: string | null
  field_type: CoaFieldType
  sort_order: number
  /** 内置字段（品名/批号/流水号）：恒定存在、必填锁定，不落库（id 为 null）。 */
  builtin?: boolean
  required?: boolean
}

/** 字段入参（全量替换语义，行序=sort_order）。 */
export interface CoaProductFieldInput {
  key: string
  label_cn: string
  label_en?: string | null
  field_type: CoaFieldType
  sort_order?: number | null
}

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
  /** text 型登记时的预填默认值（number 型恒 null）；项目必然启用（无停用态）。 */
  default_value: string | null
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
  /** text 型登记时的预填默认值（number 型传非空会被后端 422）。 */
  default_value?: string | null
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
  /** 详情接口返回：生效批次字段集（标准覆盖 ?? 产品默认）。 */
  batch_fields?: CoaProductField[]
  /** 详情接口返回：是否自定义覆盖（false=沿用产品默认）。 */
  batch_fields_custom?: boolean
  /** 详情接口返回：产品默认字段集（差异标注用）。 */
  product_fields?: CoaProductField[]
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
  /** docx 导入的批次字段草稿：与产品默认一致（或空）不落覆盖。 */
  batch_fields?: CoaProductFieldInput[] | null
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
  /** 详情/矩阵接口返回：批次信息合成视图（key=生效字段集字段键，含内置 3 键）。 */
  batch_info?: Record<string, string>
}

export interface CoaReportInput {
  product_id: string
  standard_id: string
  batch_no: string
  /** 流水号：与批号同为内置必填批次字段（品名由产品带出）。 */
  serial_no: string
  mfg_date?: string | null
  exp_date?: string | null
  issued_date?: string | null
  packaging?: string | null
  batch_size?: string | null
  storage?: string | null
  conclusion?: string | null
  remark?: string | null
  /** 模板动态批次字段值（key=生效字段集自定义键；固定列别名键后端镜像写固定列）。 */
  batch_data?: Record<string, string> | null
  values?: CoaValueInput[]
  new_items?: CoaNewItemInput[]
  raw_extract?: Record<string, unknown> | null
}

// ─────────────────────── docx 导入预览 ───────────────────────

export interface CoaStandardImportPreview {
  product: CoaProduct | null
  product_draft: CoaProductDraft
  /** 结构提取的批次信息字段标签清单（key/type 系统生成，人工可改后落库）。 */
  batch_fields_draft: CoaProductFieldInput[]
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
  /** docx 提取到的模板动态批次字段值（key=生效字段集键，确认时传 batch_data）。 */
  batch_dynamic: { key: string; label_cn: string; value: string }[]
  report_draft: {
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
  /** 各标准及其项目与生效批次字段集（出具页动态列/弹窗表单用） */
  standards: (CoaStandard & {
    items: CoaStandardItem[]
    batch_fields?: CoaProductField[]
  })[]
  rows: CoaReport[]
}
