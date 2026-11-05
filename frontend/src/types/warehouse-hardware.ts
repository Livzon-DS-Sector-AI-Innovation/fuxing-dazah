// 五金库类型定义（后端 backend/app/modules/warehouse/hardware/schemas.py 镜像）

export type HardwareManagedClass = 'stocked' | 'direct'
export type HardwareReceiptSource = 'ocr' | 'manual' | 'erp_import' | 'stocktake' | 'return'
export type HardwareReceiptStatus = 'draft' | 'accepted' | 'rejected'
export type HardwareRequisitionType = 'normal' | 'urgent' | 'excess'
export type HardwareRequisitionStatus =
  | 'draft'
  | 'pending'
  | 'approved'
  | 'issued'
  | 'rejected'
  | 'cancelled'
  | 'overdue_unpatched'
export type HardwareMovementDirection = 'inbound' | 'outbound' | 'adjust'

export const HARDWARE_MANAGED_CLASS_LABEL: Record<HardwareManagedClass, string> = {
  stocked: '共用类',
  direct: '车间单独需求',
}

export const HARDWARE_RECEIPT_SOURCE_LABEL: Record<HardwareReceiptSource, string> = {
  ocr: '拍照OCR',
  manual: '手动登记',
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
  overdue_unpatched: '超期未补单',
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

// ── 记录类型 ──

export interface HardwareMaterialRecord {
  id: string
  code: string | null
  name: string
  spec: string | null
  unit: string
  category: string
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
  /** 后端附加平铺列（列表直读免解包） */
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
  accepted_at: string | null
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
  fifo_lot_allocations?: Array<{ lot_no: string; location_id: string | null; qty: number }> | null
}

export interface HardwareRequisitionRecord {
  id: string
  req_no: string
  dept_name: string
  applicant: string
  purpose: string | null
  req_type: HardwareRequisitionType
  status: HardwareRequisitionStatus
  approval_channel?: string | null
  approval_instance_code?: string | null
  approval_status?: string | null
  approval_note?: string | null
  approved_by?: string | null
  rejected_reason?: string | null
  issued_by?: string | null
  issued_at?: string | null
  received_by?: string | null
  urgent_patch_deadline?: string | null
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

// ── 请求参数 ──

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

// ── 写操作载荷 ──

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
}

export interface HardwareReceiptAcceptInput {
  inspected_by_warehouse: string
  inspected_by_dept: string
  items?: HardwareReceiptItemInput[]
}

export interface HardwareRequisitionCreateInput {
  dept_name: string
  applicant: string
  purpose?: string
  req_type: HardwareRequisitionType
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


// ── 盘点（二期 M4）──

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

// ── 退库（二期 M4）──

export type HardwareReturnStatus = 'draft' | 'accepted' | 'rejected'

export const HARDWARE_RETURN_STATUS_LABEL: Record<HardwareReturnStatus, string> = {
  draft: '待验收',
  accepted: '已回加',
  rejected: '已拒退',
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
  dept_name: string
  returned_by: string
  items: HardwareReturnItemRecord[]
  leader_signed: boolean
  leader_signed_by: string | null
  leader_signed_at: string | null
  status: HardwareReturnStatus
  accepted_by: string | null
  accepted_at: string | null
  rejected_reason: string | null
  lot_adjustments: Array<{
    material: string
    lot_no: string | null
    mode: 'preferred' | 'new'
    qty: number
  }> | null
  remark: string | null
  created_at: string
}
