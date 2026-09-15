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
  is_system?: boolean
  created_at?: string
  updated_at?: string
}

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
