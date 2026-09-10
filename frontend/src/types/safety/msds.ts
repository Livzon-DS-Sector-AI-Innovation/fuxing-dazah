// MSDS 智能提取入库 — 类型定义

// ── AI 提取 28 字段（单个化学品）──
export interface MsdsExtractionEntry {
  name?: string | null
  cas_no?: string | null
  molecular_formula?: string | null
  un_no?: string | null
  hazard_statement?: string | null
  label_elements?: string | null
  appearance?: string | null
  solubility?: string | null
  melting_point?: string | null
  boiling_point?: string | null
  flash_point?: string | null
  relative_density?: string | null
  explosion_upper_limit?: string | null
  explosion_lower_limit?: string | null
  autoignition_temperature?: string | null
  decomposition_temperature?: string | null
  pc_twa?: string | null
  pc_stel?: string | null
  mac?: string | null
  health_hazard?: string | null
  environmental_hazard?: string | null
  first_aid?: string | null
  fire_fighting?: string | null
  leakage_response?: string | null
  waste_disposal?: string | null
  exposure_controls?: string | null
  handling_storage?: string | null
  stability_reactivity?: string | null
}

// ── 供应商资料采集记录 ──
export interface MsdsCollectionRecord {
  id: string
  feishu_record_id?: string | null
  source_date?: string | null
  attachment?: { name?: string; file_token?: string }[] | null
  person_data?: { open_id?: string; name?: string; email?: string }[] | null
  parse_status: 'pending' | 'parsed' | 'failed'
  parse_error?: string | null
  parse_result?: MsdsExtractionEntry[] | null
  msds_table_record_ids?: string[] | null
  synced_at?: string | null
  is_deleted?: boolean
  created_at?: string | null
  updated_at?: string | null
}

// ── MSDS 标准化台账 ──
export interface MsdsDocument {
  id: string
  feishu_record_id?: string | null
  collection_record_id?: string | null
  source_date?: string | null
  name?: string | null
  cas_no?: string | null
  molecular_formula?: string | null
  un_no?: string | null
  hazard_class?: string | null
  hazard_statement?: string | null
  label_elements?: string | null
  appearance?: string | null
  solubility?: string | null
  melting_point?: string | null
  boiling_point?: string | null
  flash_point?: string | null
  relative_density?: string | null
  explosion_upper_limit?: string | null
  explosion_lower_limit?: string | null
  autoignition_temperature?: string | null
  decomposition_temperature?: string | null
  pc_twa?: string | null
  pc_stel?: string | null
  mac?: string | null
  health_hazard?: string | null
  environmental_hazard?: string | null
  first_aid?: string | null
  fire_fighting?: string | null
  leakage_response?: string | null
  waste_disposal?: string | null
  exposure_controls?: string | null
  handling_storage?: string | null
  stability_reactivity?: string | null
  msds_attachment?: { name?: string; file_token?: string }[] | null
  msds_attachment_path?: string | null
  review_status: 'pending' | 'approved' | 'rejected'
  archive_status: 'pending' | 'archived'
  is_deleted?: boolean
  created_at?: string | null
  updated_at?: string | null
}

// ── 列表查询参数 ──
export interface MsdsCollectionQueryParams {
  page?: number
  page_size?: number
  parse_status?: string
  keyword?: string
}

export interface MsdsDocumentQueryParams {
  page?: number
  page_size?: number
  name?: string
  cas_no?: string
  review_status?: string
  archive_status?: string
}

// ── 统计 ──
export interface MsdsStats {
  total_collections: number
  parsed_collections: number
  failed_collections: number
  total_documents: number
  archived_documents: number
  by_parse_status: Record<string, number>
  by_review_status: Record<string, number>
}
