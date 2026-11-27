export type HardwareManagedClass = 'stocked' | 'direct'
export type HardwareReceiptSource = 'ocr' | 'manual' | 'excel' | 'erp_import' | 'stocktake' | 'return'
export type HardwareReceiptStatus = 'draft' | 'accepted' | 'rejected'
export type HardwareRequisitionType = 'normal' | 'urgent' | 'excess'
export type HardwareRequisitionStatus =
  | 'draft'
  | 'pending'
  | 'approved'
  | 'issued'
  | 'rejected'
  | 'cancelled'
export type HardwareMovementDirection = 'inbound' | 'outbound' | 'adjust'

export const HARDWARE_MANAGED_CLASS_LABEL: Record<HardwareManagedClass, string> = {
  stocked: '共用类',
  direct: '车间单独需求',
}

export const HARDWARE_RECEIPT_SOURCE_LABEL: Record<HardwareReceiptSource, string> = {
  ocr: '拍照OCR',
  manual: '手动登记',
  excel: 'Excel导入',
  erp_import: 'ERP导入',
  stocktake: '盘点盘盈',
  return: '退库回加',
}

export const HARDWARE_RECEIPT_STATUS_LABEL: Record<HardwareReceiptStatus, string> = {
  draft: '待确认',
  accepted: '已入账',
  rejected: '已拒收',
}

export const HARDWARE_REQ_TYPE_LABEL: Record<HardwareRequisitionType, string> = {
  normal: '常规',
  urgent: '紧急',
  excess: '超额',
}

export const HARDWARE_REQ_STATUS_LABEL: Record<HardwareRequisitionStatus, string> = {
  draft: '草稿',
  pending: '审批中',
  approved: '待发料',
  issued: '已发料',
  rejected: '已驳回',
  cancelled: '已取消',
}

export const HARDWARE_MOVEMENT_BIZ_LABEL: Record<string, string> = {
  receipt: '入库',
  pass_in: '直发入',
  pass_out: '直发出',
  req_issue: '领料出库',
  urgent_issue: '紧急发料',
  return_in: '退库',
  stocktake_adj: '盘点调整',
  scrap: '报废',
}

export interface HardwareMaterialRecord {
  id: string
  code: string | null
  name: string
  spec: string | null
  unit: string
  category: string
  /** 位号（默认存放位，目录级；批次级库位以入库上架为准） */
  location_no: string | null
  managed_class: HardwareManagedClass
  direct_dept?: string | null
  safety_stock: number
  monthly_demands?: Record<string, number> | null
  lead_time_days?: number | null
  secondary_holder?: string | null
  active: boolean
  remark?: string | null
}

export interface HardwareStockRow {
  material: HardwareMaterialRecord
  category?: string
  name?: string
  spec?: string | null
  unit?: string
  code?: string | null
  safety_stock?: number
  on_hand: number
  reserved: number
  available: number
  is_low: boolean
  low_gap: number
}

export interface HardwareStockSummary {
  total_materials: number
  stocked_materials: number
  low_count: number
  on_hand_total: number
  reserved_total: number
  low_materials: Array<{
    id: string
    name: string
    spec: string | null
    available: number
    safety_stock: number
  }>
}

export interface HardwareLotRow {
  lot_id: string
  lot_no: string | null
  receipt_no: string | null
  arrived_at: string | null
  expiry_date: string | null
  location_code: string | null
  remaining_quantity: number
  quantity: number
}

export interface HardwareMovementRecord {
  id: string
  movement_no: string
  direction: HardwareMovementDirection
  business_type: string
  material_id: string | null
  material_name: string
  spec?: string | null
  unit?: string | null
  lot_no?: string | null
  quantity: number
  occurred_at: string
  operator?: string | null
  dept_name?: string | null
  ref_table?: string | null
  erp_status: 'pending' | 'entered'
  remark?: string | null
}

export interface HardwareReceiptItemRecord {
  id: string
  material_id: string | null
  material_name?: string | null
  material_code?: string | null
  name: string
  spec: string | null
  unit: string | null
  quantity: number
  location_id: string | null
  lot_no: string | null
  expiry_date?: string | null
  remaining_quantity?: number | null
  match_confidence?: string | null
  match_score?: number | null
  unit_price?: number | null
  photo_screening?: HardwarePhotoScreening | null
}

export interface HardwarePhotoScreening {
  flagged: boolean
  findings: Array<{ type: string; severity: 'low' | 'mid' | 'high'; note: string }>
  overall?: string | null
  screened_at: string
  screened_by?: string
  scenario: string
  photos?: Array<string | null>
}

export interface HardwareReceiptRecord {
  id: string
  receipt_no: string
  source: HardwareReceiptSource
  mode: HardwareManagedClass
  supplier_name: string | null
  delivery_note_no: string | null
  arrived_at: string | null
  target_dept: string | null
  status: HardwareReceiptStatus
  inspected_by_warehouse: string | null
  inspected_by_dept: string | null
  rejected_reason: string | null
  erp_doc_no: string | null
  erp_imported_at?: string | null
  accepted_at: string | null
  reconcile_status?: string
  matched_receipt_id?: string | null
  auto_accepted?: boolean
  auto_accept_snapshot?: Record<string, unknown> | null
  remark?: string | null
  created_at: string
  items: HardwareReceiptItemRecord[]
}

export interface HardwareRequisitionItemRecord {
  id: string
  material_id: string
  material_name: string
  material_code: string | null
  spec: string | null
  unit: string | null
  need_qty: number
  issued_qty: number | null
  fifo_lot_allocations?: Array<{
    lot_id?: string
    lot_no: string
    location_id: string | null
    qty: number
  }> | null
}

export interface HardwareRequisitionRecord {
  id: string
  req_no: string
  dept_name: string
  applicant: string
  purpose: string | null
  req_type: HardwareRequisitionType
  status: HardwareRequisitionStatus
  approver_user_id?: string | null
  approver_name?: string | null
  approval_channel?: string | null
  approval_instance_code?: string | null
  approval_status?: string | null
  approval_note?: string | null
  approved_by?: string | null
  rejected_reason?: string | null
  issued_by?: string | null
  issued_at?: string | null
  received_by?: string | null
  urgent_reason?: string | null
  created_at: string
  items: HardwareRequisitionItemRecord[]
}

export interface HardwareLocationRecord {
  id: string
  code: string
  zone: string
  description: string | null
  active: boolean
}

export interface HardwareStockFilter {
  keyword?: string
  category?: string
  managed_class?: string
  low_only?: boolean
  page?: number
  pageSize?: number
}

export interface HardwareMovementFilter {
  direction?: string
  business_type?: string
  keyword?: string
  dept_name?: string
  erp_status?: string
  page?: number
  pageSize?: number
}

export interface HardwareReceiptFilter {
  status?: string
  source?: string
  keyword?: string
  page?: number
  pageSize?: number
}

export interface HardwareRequisitionFilter {
  status?: string
  dept_name?: string
  req_type?: string
  keyword?: string
  page?: number
  pageSize?: number
}

export interface HardwareReceiptItemInput {
  material_id?: string | null
  name: string
  spec?: string | null
  unit?: string | null
  quantity: number
  location_id?: string | null
  expiry_date?: string | null
  match_confidence?: string
  match_score?: number
  unit_price?: number
}

export interface HardwareReceiptCreateInput {
  source: HardwareReceiptSource
  mode: HardwareManagedClass
  supplier_name?: string
  delivery_note_no?: string
  arrived_at?: string
  target_dept?: string
  remark?: string
  items: HardwareReceiptItemInput[]
  ocr_result?: Record<string, unknown> | null
  excel_result?: Record<string, unknown> | null
}

export interface HardwareReceiptParseItem extends HardwareReceiptItemInput {
  matched_name?: string | null
  low_confidence?: boolean
  managed_class?: string | null
}

export interface HardwareReceiptParseDocument {
  key: string
  delivery_note_no?: string | null
  supplier_name?: string | null
  item_indexes: number[]
  stocked_count: number
  direct_count: number
  unmatched_count: number
  all_matched: boolean
  mode: HardwareManagedClass
}

export interface HardwareReceiptParseResult {
  mode: HardwareManagedClass
  supplier_name?: string | null
  delivery_note_no?: string | null
  remark?: string | null
  target_dept?: string | null
  items: HardwareReceiptParseItem[]
  documents?: HardwareReceiptParseDocument[]
  match_summary: Array<Record<string, unknown>>
  matched_stocked: number
  matched_direct: number
  unmatched: number
  errors: Array<{ row: number; name: string; reason: string }>
  excel_result: Record<string, unknown> | null
  ocr_result?: Record<string, unknown> | null
}

export interface HardwareReceiptAcceptInput {
  inspected_by_warehouse: string
  inspected_by_dept?: string
  items?: HardwareReceiptItemInput[]
}

export interface HardwareRequisitionCreateInput {
  dept_name: string
  applicant: string
  approver_user_id?: string
  approver_name?: string
  purpose?: string
  req_type: HardwareRequisitionType
  urgent_reason?: string
  items: Array<{ material_id: string; need_qty: number }>
}

export interface HardwareRequisitionIssueInput {
  issued_by: string
  received_by: string
  items: Array<{ item_id: string; issued_qty: number }>
}

export interface HardwareImportStats {
  total_rows: number
  created: number
  updated: number
  skipped: number
  errors: string[]
}

export type HardwareStocktakeType = 'monthly' | 'annual' | 'special' | 'calibration'
export type HardwareStocktakeStatus =
  | 'draft'
  | 'counting'
  | 'reviewed'
  | 'confirmed'
  | 'cancelled'

export const HARDWARE_STOCKTAKE_TYPE_LABEL: Record<HardwareStocktakeType, string> = {
  monthly: '月度盘点',
  annual: '年度盘点',
  special: '专项盘点',
  calibration: '期初校准',
}

export const HARDWARE_STOCKTAKE_STATUS_LABEL: Record<HardwareStocktakeStatus, string> = {
  draft: '待实盘',
  counting: '实盘中',
  reviewed: '待确认',
  confirmed: '已入账',
  cancelled: '已作废',
}

export interface HardwareStocktakeItemRecord {
  id: string
  material_id: string
  code: string | null
  name: string
  spec: string | null
  unit: string | null
  unit_price: number | null
  book_qty: number
  actual_qty: number | null
  diff_qty: number | null
  diff_amount: number | null
  explanation: string | null
}

export interface HardwareStocktakeRecord {
  id: string
  take_no: string
  take_type: HardwareStocktakeType
  status: HardwareStocktakeStatus
  snapshot_at: string | null
  summary_note: string | null
  diff_surplus_items: number | null
  diff_deficit_items: number | null
  diff_total_amount: number | null
  explained_by: string | null
  explained_at: string | null
  confirmed_by: string | null
  confirmed_at: string | null
  remark: string | null
  created_at: string
  items?: HardwareStocktakeItemRecord[]
}

/** 平台发起链路：draft 待提交 → pending 待审批 → approved 待验收 → accepted 已回加；
 * 老登记/飞书自建链路：draft=待签收验收。channel 为空即老链路。 */
export type HardwareReturnStatus =
  | 'draft'
  | 'pending'
  | 'approved'
  | 'accepted'
  | 'rejected'
  | 'cancelled'

export const HARDWARE_RETURN_STATUS_LABEL: Record<HardwareReturnStatus, string> = {
  draft: '待提交',
  pending: '待审批',
  approved: '待验收',
  accepted: '已回加',
  rejected: '已驳回',
  cancelled: '已撤回',
}

export interface HardwareReturnItemRecord {
  material_id: string
  code: string | null
  name: string
  spec: string | null
  unit: string | null
  quantity: string
  preferred_lot_id: string | null
}

export interface HardwareReturnRecord {
  id: string
  return_no: string
  requisition_id: string | null
  requisition_instance_code: string | null
  approver_user_id: string | null
  approver_name: string | null
  approval_channel: string | null
  approval_instance_code: string | null
  approval_status: string | null
  dept_name: string
  returned_by: string
  items: HardwareReturnItemRecord[]
  leader_signed: boolean
  leader_signed_by: string | null
  leader_signed_at: string | null
  status: HardwareReturnStatus
  accepted_by: string | null
  accepted_at: string | null
  rejected_by: string | null
  rejected_reason: string | null
  lot_adjustments: Array<{
    material: string
    lot_no: string | null
    mode: 'preferred' | 'new'
    qty: number
  }> | null
  remark: string | null
  created_at: string
  /** 当前用户能否在平台点通过/驳回（退料管理权限或所选审批人） */
  can_approve?: boolean
}

/** 领料单可退额度行（退料弹窗逐行上限） */
export interface HardwareReturnableRow {
  material_id: string
  name: string | null
  spec: string | null
  unit: string | null
  issued: number
  returned: number
  returnable: number
}

export interface HardwareReturnFromRequisitionInput {
  requisition_id: string
  returned_by?: string
  approver_user_id?: string
  approver_name?: string
  reason_note?: string
  items: Array<{ material_id: string; quantity: number; preferred_lot_id?: string }>
}

export interface HardwarePlanItemRecord {
  id: string
  material_id: string
  code: string | null
  name: string
  spec: string | null
  unit: string | null
  monthly_demand_total: number
  safety_stock: number
  stock_on_25th: number
  monthly_usage: number
  purchase_qty: number
  ai_note: string | null
  is_edited: boolean
  remark: string | null
}

export interface HardwarePlanRecord {
  id: string
  plan_month: string
  status: 'draft' | 'exported'
  snapshot_at: string | null
  usage_window_days: number
  annotated: boolean
  exported_at: string | null
  remark: string | null
  created_at: string
  items?: HardwarePlanItemRecord[]
}

export interface HardwareEnvLogRecord {
  id: string
  log_date: string
  temperature: number | null
  humidity: number | null
  checked_by: string | null
  abnormal_note: string | null
}

export type HardwareScrapReason = 'expired' | 'damaged' | 'obsolete' | 'appraisal'
/** 报废单状态与领料单同名同义：待审批 → 待出库 → 已出库（走同一条出库路径） */
export type HardwareScrapStatus =
  | 'draft'
  | 'pending'
  | 'approved'
  | 'issued'
  | 'rejected'
  | 'cancelled'

export const HARDWARE_SCRAP_REASON_LABEL: Record<HardwareScrapReason, string> = {
  expired: '超有效期',
  damaged: '破损污染变质',
  obsolete: '工艺淘汰',
  appraisal: '技术鉴定失效',
}

export const HARDWARE_SCRAP_STATUS_LABEL: Record<HardwareScrapStatus, string> = {
  draft: '草稿',
  pending: '待审批',
  approved: '待出库',
  issued: '已出库',
  rejected: '已驳回',
  cancelled: '已撤回',
}

export interface HardwareScrapItemRecord {
  id: string
  material_id: string
  quantity: number
  preferred_lot_id: string | null
  name: string
  spec: string | null
  unit: string | null
  unit_price: number | null
}

export interface HardwareScrapRecord {
  id: string
  scrap_no: string
  dept_name: string
  requested_by: string
  scrap_reason: HardwareScrapReason
  reason_note: string | null
  attachments: Array<Record<string, unknown>> | null
  approver_user_id: string | null
  approver_name: string | null
  approval_channel: string | null
  approval_instance_code: string | null
  approval_status: string | null
  approved_by: string | null
  approved_at: string | null
  executed_by: string | null
  rejected_by: string | null
  rejected_reason: string | null
  status: HardwareScrapStatus
  scrapped_at: string | null
  lot_allocations: Array<Record<string, unknown>> | null
  remark: string | null
  created_at: string
  items?: HardwareScrapItemRecord[]
  /** 当前用户能否在平台点通过/驳回（报废管理权限或所选审批人） */
  can_approve?: boolean
}

/** 「申请单据」合并列表的一行：领料单或报废单（doc_kind 指明），另一侧为 null */
export interface HardwareOutboundDocRow {
  doc_kind: 'requisition' | 'scrap'
  id: string
  requisition: HardwareRequisitionRecord | null
  scrap: HardwareScrapRecord | null
}

export interface HardwareScrapCreateInput {
  dept_name: string
  requested_by: string
  approver_user_id?: string
  approver_name?: string
  scrap_reason: HardwareScrapReason
  reason_note?: string
  remark?: string
  items: Array<{ material_id: string; quantity: number; preferred_lot_id?: string }>
}

export interface HardwareErpImportResult {
  created: number
  skipped: number
  auto_accepted?: number
  reconcile?: { matched: number; unmatched: number }
  receipts: Array<{
    receipt_id: string
    receipt_no: string
    erp_doc_no: string
    mode: HardwareManagedClass
    rows: number
    matched_stocked: number
    matched_direct: number
    unmatched: number
    reconcile_status?: string
    auto_accepted?: boolean
  }>
}

export interface HardwareReconcileDiffs {
  erp_only: HardwareReconcileHead[]
  ocr_only: HardwareReconcileHead[]
}

export interface HardwareReconcileHead {
  receipt_id: string
  receipt_no: string
  erp_doc_no: string | null
  supplier_name: string | null
  arrived_at: string | null
  status: HardwareReceiptStatus
  mode: HardwareManagedClass
  reconcile_status: string
}

export const HARDWARE_RECONCILE_STATUS_LABEL: Record<string, string> = {
  none: '未核对',
  unmatched: '未匹配',
  matched: '已匹配',
  verified: '核对通过',
  discrepancy: '差异',
}
