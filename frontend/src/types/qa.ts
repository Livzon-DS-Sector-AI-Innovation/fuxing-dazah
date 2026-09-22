/**
 * QA 模块前端契约。
 *
 * QA 的对象故意与 quality（质量检验）和 hr.qa_assessments（培训考核）分开，
 * 这里仅描述文件台账、主数据以及搜索所需的最小字段。后端新增字段时，
 * 由于接口响应可能来自不同版本，部分展示字段保留了兼容别名。
 */

export const QA_MASTER_KINDS = ['PRODUCT', 'MATERIAL', 'EQUIPMENT', 'SUPPLIER', 'REGION'] as const
export type QaMasterKind = (typeof QA_MASTER_KINDS)[number]

export const QA_MASTER_KIND_LABELS: Record<QaMasterKind, string> = {
  PRODUCT: '产品',
  MATERIAL: '物料',
  EQUIPMENT: '设备',
  SUPPLIER: '供应商',
  REGION: '区域',
}

export interface QaDepartmentReference {
  id: string
  feishu_department_id?: string | null
  name: string
  parent_feishu_department_id?: string | null
  path?: string | null
  is_deleted?: boolean
  available?: boolean
  is_active?: boolean
}

export interface QaSourceReference {
  id: string
  code?: string | null
  name: string
  source_module: string
  source_entity: string
  source_id: string
  is_active?: boolean
  is_deleted?: boolean
  category?: string | null
  is_product?: boolean
  source?: 'own_scope' | 'shared' | string | null
}

export interface QaMasterSource {
  id?: string
  source_module: string
  source_entity: string
  source_id: string
  source_code?: string | null
  source_name?: string | null
  code_snapshot?: string | null
  name_snapshot?: string | null
  source_code_snapshot?: string | null
  source_name_snapshot?: string | null
  source_available?: boolean
  is_active?: boolean
}

export interface QaMasterAlias {
  id?: string
  alias: string
  normalized_alias?: string
  is_active?: boolean
}

export interface QaMasterObject {
  id: string
  kind: QaMasterKind
  object_type?: QaMasterKind
  type?: QaMasterKind
  code: string
  business_code?: string
  name: string
  description?: string | null
  is_active?: boolean
  status?: 'active' | 'inactive' | string
  responsible_department_id?: string | null
  responsible_department_name?: string | null
  department_id?: string | null
  department_name?: string | null
  parent_id?: string | null
  region_parent_id?: string | null
  responsible_department_name_snapshot?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_email?: string | null
  remark?: string | null
  aliases?: QaMasterAlias[]
  sources?: QaMasterSource[]
  source_count?: number
  related_document_count?: number
  created_at?: string
  updated_at?: string
}

export interface QaMasterObjectInput {
  kind: QaMasterKind
  code: string
  name: string
  description?: string | null
  responsible_department_id?: string | null
  responsible_department_name?: string | null
  parent_id?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_email?: string | null
  remark?: string | null
  aliases?: string[]
  sources?: Array<{
    source_module: string
    source_entity: string
    source_id: string
  }>
}

export interface QaDocumentType {
  id: string
  code: string
  name: string
  is_active?: boolean
  status?: 'active' | 'inactive' | string
  description?: string | null
  ai_source_policy?: 'authoritative' | 'reference' | 'disabled' | string
  is_system?: boolean
  created_at?: string
  updated_at?: string
}

/** 台账排序字段，与后端 DOCUMENT_SORT_COLUMNS 白名单一一对应。 */
export type QaDocumentSort = 'document_no' | 'title'

export interface QaDocument {
  id: string
  document_no: string
  file_no?: string
  title: string
  document_type_id?: string | null
  document_type_code?: string | null
  document_type_name?: string | null
  document_type?: QaDocumentType | null
  responsible_department_id?: string | null
  responsible_department_name?: string | null
  department_id?: string | null
  department_name?: string | null
  responsible_department_name_snapshot?: string | null
  is_active?: boolean
  status?: 'active' | 'inactive' | string
  current_version_id?: string | null
  current_version_label?: string | null
  current_extraction_status?: string | null
  current_version?: QaDocumentVersion | null
  versions?: QaDocumentVersion[]
  version_count?: number
  created_at?: string
  updated_at?: string
}

export interface QaDocumentInput {
  document_no: string
  title: string
  document_type_id: string
  responsible_department_id?: string | null
  responsible_department_name?: string | null
}

export type QaVersionState = 'registered' | 'current' | 'history' | 'inactive' | string

export interface QaDocumentVersion {
  id: string
  document_id: string
  version_label: string
  sequence?: number
  version_no?: number
  state?: QaVersionState
  status?: QaVersionState
  approved_declared: boolean
  is_active?: boolean
  locked_at?: string | null
  first_locked_at?: string | null
  created_at?: string
  created_by?: string | null
  file?: QaDocumentFile | null
  files?: QaDocumentFile[]
  relations?: QaDocumentMasterLink[]
  relation_count?: number
}

export interface QaDocumentFile {
  id: string
  version_id?: string
  original_filename: string
  filename?: string
  extension?: string | null
  mime_type?: string | null
  size_bytes?: number
  file_size?: number
  sha256?: string | null
  extraction_status?: 'queued' | 'processing' | 'ready' | 'text_not_available' | 'unsupported' | 'failed' | string
  extraction_error?: string | null
  retry_count?: number
  content_url?: string
  preview_url?: string
  created_at?: string
  parser_mode?: string
  parser_version?: string | null
  current_extraction_run_id?: string | null
  current_chunk_run_id?: string | null
  legacy?: boolean
}

export type QaDocumentProcessingView = 'raw_blocks' | 'chunks'

/** 一次正文解析运行的只读摘要。latest 可能是正在处理/失败的运行，current 才是当前有效证据。 */
export interface QaDocumentExtractionRunSummary {
  id: string
  status: string
  is_current: boolean
  parser_mode: string
  parser_version: string
  block_count: number
  char_count: number
  statistics?: Record<string, unknown> | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

/** 由 raw block 确定性派生的一次分块运行摘要。 */
export interface QaDocumentChunkRunSummary {
  id: string
  status: string
  is_current: boolean
  extraction_run_id: string
  chunk_version: string
  chunk_count: number
  char_count: number
  statistics?: Record<string, unknown> | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

export interface QaDocumentRawBlock {
  id: string
  source_order?: number | null
  block_type: string
  locator: string
  page_number?: number | null
  paragraph_index?: number | null
  table_index?: number | null
  row_index?: number | null
  column_index?: number | null
  heading_path?: string[] | null
  content_preview: string
  content_length: number
  content_truncated: boolean
  text_hash: string
  structure_metadata?: Record<string, unknown> | null
}

export interface QaDocumentChunkSourceBlock {
  segment_id: string
  block_order: number
  char_start?: number | null
  char_end?: number | null
  locator?: string | null
  block_type?: string | null
}

export interface QaDocumentTextChunk {
  id: string
  chunk_order: number
  char_count: number
  /** 后端为后续模型限长保留；文件详情查看器不展示 token 统计。 */
  token_count: number
  heading_path?: string[] | null
  page_start?: number | null
  page_end?: number | null
  source_start?: number | null
  source_end?: number | null
  content_preview: string
  content_truncated: boolean
  content_hash: string
  metadata?: Record<string, unknown> | null
  source_blocks: QaDocumentChunkSourceBlock[]
}

/** 文件解析/分块查看接口；明细始终来自 current 运行，latest 只用于展示任务状态。 */
export interface QaDocumentProcessingResult {
  file_id: string
  extraction_status: string
  extraction_error?: string | null
  retry_count: number
  parser_mode: string
  parser_version?: string | null
  legacy: boolean
  current_extraction_run?: QaDocumentExtractionRunSummary | null
  latest_extraction_run?: QaDocumentExtractionRunSummary | null
  current_chunk_run?: QaDocumentChunkRunSummary | null
  latest_chunk_run?: QaDocumentChunkRunSummary | null
  view: QaDocumentProcessingView
  page: number
  page_size: number
  total: number
  raw_blocks: QaDocumentRawBlock[]
  chunks: QaDocumentTextChunk[]
}

export interface QaDocumentMasterLink {
  id?: string
  version_id?: string
  master_object_id: string
  master_object_kind?: QaMasterKind
  master_object_code?: string | null
  master_object_name?: string | null
  relation_type?: 'APPLIES_TO' | string
  code_snapshot?: string | null
  name_snapshot?: string | null
  source_available?: boolean
}

export interface QaSearchResult {
  id: string
  kind: 'master_object' | 'master' | 'document' | 'department' | string
  score?: number
  title?: string
  name?: string
  code?: string | null
  document_no?: string | null
  document_id?: string | null
  version_id?: string | null
  object_type?: QaMasterKind | string | null
  master_object?: QaMasterObject | null
  document?: QaDocument | null
  department?: QaDepartmentReference | null
  snippet?: string | null
  locator?: string | null
  page_number?: number | null
  paragraph_index?: number | null
  segment_type?: string | null
  is_current?: boolean
  is_active?: boolean
}

export interface QaAuditLog {
  id: string
  action: string
  object_type?: string | null
  object_id?: string | null
  resource_type?: string | null
  resource_id?: string | null
  user_id?: string | null
  actor_id?: string | null
  actor_name?: string | null
  created_at: string
  before_value?: Record<string, unknown> | null
  after_value?: Record<string, unknown> | null
  metadata?: Record<string, unknown> | null
  file_sha256?: string | null
  ip_address?: string | null
}

export interface QaPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface QaSearchPage {
  items: QaSearchResult[]
  total: number
  page: number
  page_size: number
}

export type QaAiAnalysisStatus = 'queued' | 'processing' | 'ready' | 'partial' | 'failed' | 'stale' | string

export interface QaAiObservation {
  id: string
  chunk_id?: string | null
  raw_block_id?: string | null
  mention_text: string
  normalized_text: string
  entity_type: string
  quote: string
  evidence_hash?: string
  locator: string
  page_number?: number | null
  paragraph_index?: number | null
  table_index?: number | null
  row_index?: number | null
  column_index?: number | null
  source_order?: number | null
  confidence?: number
  extraction_method?: string
  normalization_hint?: string | null
  observation_metadata?: Record<string, unknown> | null
}

export interface QaAiRelationSuggestion {
  id: string
  observation_id: string
  master_object_id: string
  relation_type: string
  match_method: string
  rank: number
  confidence: number
  selected_by_default: boolean
  status: string
  rationale?: string | null
}

export interface QaMasterObjectProposal {
  id: string
  analysis_run_id: string
  observation_id?: string | null
  proposal_type: 'create' | 'update' | string
  target_master_object_id?: string | null
  object_type: QaMasterKind | string
  proposed_payload: Record<string, unknown>
  field_diffs?: Record<string, unknown> | null
  evidence?: Array<Record<string, unknown>> | null
  conflicts?: Array<Record<string, unknown>> | null
  base_snapshot?: Record<string, unknown> | null
  base_fingerprint?: string | null
  /** 仅审批接口返回：提案通过后文件关联是否已自动建立 */
  auto_linked?: boolean
  auto_link_skipped_reason?: string | null
  status: string
  created_at?: string
  reviewed_at?: string | null
}

export interface QaAiAnalysisRun {
  id: string
  version_id: string
  file_id: string
  extraction_run_id?: string | null
  chunk_run_id?: string | null
  status: QaAiAnalysisStatus
  provider: string
  model: string
  prompt_version: string
  schema_version: string
  source_policy: string
  catalog_fingerprint: string
  input_fingerprint: string
  processed_chunks: number
  total_chunks: number
  entity_count: number
  suggestion_count: number
  proposal_count: number
  error?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  observations: QaAiObservation[]
  suggestions: QaAiRelationSuggestion[]
  proposals: QaMasterObjectProposal[]
}
