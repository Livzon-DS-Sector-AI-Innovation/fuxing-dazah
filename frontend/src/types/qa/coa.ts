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
  /** 模板状态：none=没上传 docx；unbound=已上传未确认标注；bound=标注已确认（可生成 COA）。 */
  template_status?: CoaTemplateStatus
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
  packaging: string | null
  batch_size: string | null
  storage: string | null
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
  packaging?: string | null
  batch_size?: string | null
  storage?: string | null
  remark?: string | null
  /** 模板动态批次字段值（key=生效字段集自定义键；固定列别名键后端镜像写固定列）。 */
  batch_data?: Record<string, string> | null
  values?: CoaValueInput[]
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
    packaging: string | null
    batch_size: string | null
    storage: string | null
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

// ─────────────────────── 模板标注与回填 ───────────────────────

/** none=没上传模板；unbound=已上传未确认标注；bound=标注已确认；
 *  stale=标注确认后字段配置变了，要重新核对并保存才能生成 COA */
export type CoaTemplateStatus = 'none' | 'unbound' | 'bound' | 'stale'

/** 标注确认之后字段配置的变化：已保存的标注因此要重新核对。 */
export interface CoaTemplateDrift {
  /** 标注引用的字段/项目已被移除，那一条标注不再生效 */
  removed: { field: string; label_cn: string }[]
  /** 确认之后新增、还没标注位置的字段 */
  added: { field: string; label_cn: string; kind: 'batch' | 'item' }[]
  /** 类型/单位变了的字段：已确认的格式规则要重新过目 */
  changed: { field: string; label_cn: string; changes: string[] }[]
  /** 给人看的条目（要动手的排前面）；生成被拦时的报错也是这一套说法 */
  lines: string[]
}

/** 数据位的格式规则：登记的值 → 写进 docx 的文字（只列该类型用得到的键）。 */
export interface CoaTemplateFmt {
  kind: 'number' | 'date' | 'text'
  /** 数值：小数位数（四舍五入） */
  decimals?: number
  /** 跟在值后面的单位，如 %、IU/mg */
  suffix?: string
  /** 日期：strftime 写法，如 %Y.%m.%d */
  pattern?: string
  /** 文字判定是否补英文（符合规定 → 符合规定Conform；英文查自判定词对照） */
  bilingual?: boolean
  /** 中文与英文之间：无间隔 / 空格 / 换行 */
  joiner?: '' | ' ' | '\n'
}

export interface CoaTemplateSlot {
  /** 数据位地址：正文段落 P1、表格 T0.R2.G3.p0（G=表格网格列）、页眉 H.P0 */
  sid: string
  /** replace=整段就是值；inplace=值夹在固定文字中间（标题行流水号） */
  mode: 'replace' | 'inplace'
  /** 模板里当前要被替换的文字（整格=整格文字；空格为空串） */
  sample: string
  fmt: CoaTemplateFmt
  /** 所在行里其他格的文字（项目名、标准），核对「是不是这一行」 */
  context: string
  /** 确定性校验标记（文案见 flag_labels），空=自动核对通过 */
  flags: string[]
}

export interface CoaTemplateField {
  /** batch:<字段键> | item:<项目 id> */
  field: string
  kind: 'batch' | 'item'
  label_cn: string
  label_en: string | null
  type: CoaFieldType | null
  unit: string | null
  spec_text: string | null
  value_type: CoaValueType | null
  /** 有没有标注到位置 */
  bound: boolean
  /** 回填时该字段必须有值（没值拦截并列出缺项） */
  required: boolean
  slots: CoaTemplateSlot[]
  flags: string[]
}

/** 结果列里没绑定又非空的格子：必须绑定到字段，或确认是固定文字。 */
export interface CoaTemplateResidue {
  sid: string
  text: string
  context: string
}

/** 模板网格：按原文顺序列出段落与表格（含跨列/跨行标记），供前端画预览。 */
export interface CoaTemplateGridPara {
  sid: string
  text: string
  /** 段落对齐（CSS text-align 的值）；没带 = 左对齐 */
  align?: 'center' | 'end' | 'justify'
}

export interface CoaTemplateGridCell {
  sid: string
  col: number
  span: number
  vmerge: 'restart' | 'cont' | null
  hmerge: 'restart' | 'cont' | null
  paras: CoaTemplateGridPara[]
}

export interface CoaTemplateGridRow {
  sid: string
  cells: CoaTemplateGridCell[]
}

export type CoaTemplateGridBlock =
  | ({ type: 'p' } & CoaTemplateGridPara)
  | {
      type: 'table'
      sid: string
      ncols: number
      /** 网格各列宽度（缇）：预览按真实比例画列；文件没写列宽时没有 */
      col_widths?: number[]
      rows: CoaTemplateGridRow[]
    }
  | { type: 'textbox'; sid: string; blocks: CoaTemplateGridBlock[] }

export interface CoaTemplateGridSection {
  part: 'document' | 'header' | 'footer'
  title: string
  sid: string | null
  blocks: CoaTemplateGridBlock[]
}

export interface CoaTemplateInfo {
  status: CoaTemplateStatus
  filename: string | null
  sha256: string | null
  bound_at: string | null
  prompt_version: string | null
}

/** 标注视图：AI 提案与已保存的标注同形。 */
export interface CoaTemplateBindingView {
  defaults: {
    decimals: number
    verdict_bilingual: boolean
    joiner: string
    date_pattern: string
  }
  /** 判定词中→英对照（模板样例里学到的，可增改；内置常用词之外的部分） */
  verdicts: Record<string, string>
  fields: CoaTemplateField[]
  /** 确认「保持模板原文」的数据位 */
  static_slots: string[]
  residue: CoaTemplateResidue[]
  /** 模型自己报告没找到位置的字段 */
  ai_unmapped: { field: string; label_cn: string; kind: string }[]
  /** 模型输出里被丢弃的绑定及原因 */
  problems: string[]
  flag_labels: Record<string, string>
  needs_review: number
}

/** 项目表的「结果列」：表地址 → 网格列号（T1 → 3）。 */
export type CoaResultColumns = Record<string, number>

export interface CoaTemplateState {
  template: CoaTemplateInfo
  grid?: CoaTemplateGridSection[]
  result_columns?: CoaResultColumns
  /** 标注确认后字段配置有变化时才有；对得上为 null */
  drift?: CoaTemplateDrift | null
  binding: CoaTemplateBindingView | null
}

export interface CoaTemplateAnnotateResult extends CoaTemplateBindingView {
  template: CoaTemplateInfo
  grid: CoaTemplateGridSection[]
  result_columns: CoaResultColumns
  prompt_version: string
}

/** 「确认标注并保存」的入参（后端会对模板重新校验一遍）。 */
export interface CoaTemplateBindingInput {
  fields: {
    field: string
    required: boolean
    slots: { sid: string; fmt: CoaTemplateFmt; sample?: string | null }[]
  }[]
  static_slots: string[]
  verdicts: Record<string, string>
}

export type CoaRenderBlocking =
  /** 必填字段没有登记值 */
  | { kind: 'missing'; field: string; label: string; item: boolean }
  /** 模板的旧批号/旧日期还留在输出里：有位置没标到 */
  | { kind: 'stale'; sample: string; found_in: string[] }

export type CoaRenderWarning =
  /** 开了补英文但判定词对照里没有 */
  | { kind: 'no_english'; field: string; label: string; text: string }
  /** 有登记值但没标注到模板的项目（不会出现在 COA 上） */
  | { kind: 'unbound_items'; count: number; labels: string[] }
  /** 有登记值但没标注到模板的批次信息（不会出现在 COA 上） */
  | { kind: 'unbound_batch'; count: number; labels: string[] }

/** 生成 COA 的预检结果：blocking 非空不许生成；warnings 提示后可继续。 */
export interface CoaRenderCheck {
  ok: boolean
  filename: string
  /** 模板文件名：下载前告诉用户这次按哪份模板出 */
  template?: string | null
  /** 这次写进模板的内容概要（被清空的位置不算） */
  written?: { batch: number; items: number; positions: number }
  blocking: CoaRenderBlocking[]
  warnings: CoaRenderWarning[]
}

// ─────────────────────── 生成留档与验证 ───────────────────────

/** 生成留档：每生成（下载）一次 COA 一条，只增不改不删。 */
export interface CoaRenderRecord {
  id: string
  report_id: string
  product_id: string
  product_name: string | null
  standard_id: string
  standard_code: string
  batch_no: string
  filename: string
  file_sha256: string
  template_sha256: string | null
  /** 系统写入的数据位数 */
  positions: number
  created_at: string
  actor_id: string | null
  actor_name: string | null
  /** 所属登记此后已被作废（留档仍然保留） */
  report_voided: boolean
}

/**
 * 验证结论：
 * identical=与留档字节一致；content_match=字节不同但文字全同（被重新保存过）；
 * altered=有位置对不上；no_record=系统没有这个批号的生成记录。
 */
export type CoaVerifyVerdict = 'identical' | 'content_match' | 'altered' | 'no_record'

/** 比对范围：bytes=只比了哈希；full_text=全部文字；written_only=留档原件已不在，只比了系统写入的位置。 */
export type CoaVerifyScope = 'bytes' | 'full_text' | 'written_only' | null

/** 一个系统写入位置的比对结果。 */
export interface CoaVerifySlot {
  field: string
  label: string
  item: boolean
  sid: string
  mode: 'replace' | 'inplace'
  /** 系统原件里写入的文字 */
  expected: string
  /** 上传文件里同一位置的文字；文件里找不到这一位时为 null */
  actual: string | null
  status: 'match' | 'differs' | 'context_differs' | 'missing_position'
}

/** 系统没写入的位置上的差异。 */
export interface CoaVerifyDifference {
  where: '正文' | '页眉' | '页脚'
  sid: string
  expected: string | null
  actual: string | null
  status: 'differs' | 'missing_position' | 'added'
}

export interface CoaVerifyResult {
  verdict: CoaVerifyVerdict
  uploaded_sha256: string
  /** 对上的那条留档；没有生成记录时为 null */
  record: CoaRenderRecord | null
  /** 同一份报告其余次的生成记录（旧版） */
  other_records: CoaRenderRecord[]
  matched_by: 'sha256' | 'batch_no' | 'report_id' | null
  scope: CoaVerifyScope
  /** 指定了报告比对时的报告 */
  report: { id: string; batch_no: string } | null
  slots: CoaVerifySlot[]
  other_differences: CoaVerifyDifference[]
  compared: number
  /** 对不上的处数（含系统没写入的位置） */
  differing: number
  /** 系统写入的位置里，文件中找不到的处数 */
  unresolved: number
}
