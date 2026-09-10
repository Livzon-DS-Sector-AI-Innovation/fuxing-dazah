
// ============ 相关方准入条件审核（contractor-admission） ============
// 与后端 app/modules/safety/schemas/contractor_admission.py 对齐

/** 附件项（Bitable attachment 镜像，元素结构 {name, path, file_token, original_name}） */
export interface AdmissionAttachmentItem {
  name?: string | null
  path?: string | null
  file_token?: string | null
  original_name?: string | null
}

/** AI 审核单维度结果（agreement/license/insurance） */
export interface AdmissionDimensionResult {
  conclusion?: string | null // 审核通过/需补充完善/审核不通过
  report?: string | null
  defects?: string[]
}

/** ai_review_result JSONB 投影 */
export interface AdmissionReviewResult {
  agreement?: AdmissionDimensionResult | null
  license?: AdmissionDimensionResult | null
  insurance?: AdmissionDimensionResult | null
  overall_conclusion?: string | null
  overall_report?: string | null
  defect_categories?: string[] // A基础信息类/B有效期类/C签章类/D骑缝章类
  regulations?: { doc_title?: string; article_ref?: string }[]
}

/** 列表项（轻量，不含大 JSON；ai_overall_conclusion 由后端平铺） */
export interface ContractorAdmissionListItem {
  id: string
  company_name?: string | null
  related_party_type?: string | null // 承包商/合作类相关方/劳务派遣/其他相关方
  contact_person?: string | null
  liaison_user_name?: string | null
  entry_date?: string | null
  submit_status?: string | null // 已完成/进行中/未开始
  training_status?: string | null // 已完结/已培训待补材/未培训
  ai_review_status?: string // none/processing/completed/failed
  ai_overall_conclusion?: string | null // 审核通过/需补充完善/审核不通过
  created_at: string
  updated_at: string
}

/** 详情 */
export interface ContractorAdmission {
  id: string
  admission_no?: string | null
  company_name?: string | null
  related_party_type?: string | null
  contact_person?: string | null
  contact_phone?: string | null
  liaison_user_id?: string | null
  liaison_user_name?: string | null
  entry_date?: string | null
  start_date?: string | null
  end_date?: string | null
  material_expiry_date?: string | null
  actual_submit_date?: string | null
  actual_complete_date?: string | null
  submit_status?: string | null
  training_status?: string | null
  notes?: string | null
  safety_agreement_files?: AdmissionAttachmentItem[] | null
  business_license_files?: AdmissionAttachmentItem[] | null
  insurance_files?: AdmissionAttachmentItem[] | null
  assessment_rules_files?: AdmissionAttachmentItem[] | null
  employee_cert_files?: AdmissionAttachmentItem[] | null
  on_site_leader_stamp_files?: AdmissionAttachmentItem[] | null
  // Bitable 同步字段
  source?: string // bitable/manual
  feishu_record_id?: string | null
  feishu_table_id?: string | null
  feishu_url?: string | null
  // AI 审核
  ai_review_status?: string // none/processing/completed/failed
  ai_review_result?: AdmissionReviewResult | null
  ai_error_message?: string | null
  ai_reviewed_at?: string | null
  created_at: string
  updated_at: string
}

/** 列表查询参数（与后端 Query 参数对齐） */
export interface ContractorAdmissionQueryParams {
  page?: number
  page_size?: number
  related_party_type?: string
  submit_status?: string
  ai_review_status?: string
  ai_conclusion?: string
  keyword?: string
  sort_by?: string
  sort_order?: string
}

/** KPI 统计（stats 端点） */
export interface ContractorAdmissionStats {
  total: number
  by_ai_review_status: Record<string, number> // none/processing/completed/failed
  by_related_party_type: Record<string, number>
  by_submit_status: Record<string, number>
}
