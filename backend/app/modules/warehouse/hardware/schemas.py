"""五金库 request/response schemas（warehouse.hardware）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

StrUUID = str

ManagedClass = Literal["stocked", "direct"]
ReceiptSource = Literal["ocr", "manual", "erp_import", "stocktake", "return"]
ReceiptStatus = Literal["draft", "accepted", "rejected"]
RequisitionType = Literal["normal", "urgent", "excess"]
RequisitionStatus = Literal[
    "draft", "pending", "approved", "issued", "rejected", "cancelled", "overdue_unpatched"
]
MovementDirection = Literal["inbound", "outbound", "adjust"]
StocktakeType = Literal["monthly", "annual", "special", "calibration"]
StocktakeStatus = Literal["draft", "counting", "reviewed", "confirmed", "cancelled"]
ReturnStatus = Literal["draft", "accepted", "rejected"]


# ── 物料主数据 ──


class MaterialCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="物资名称")
    spec: str | None = Field(default=None, max_length=200, description="规格型号")
    unit: str = Field(..., min_length=1, max_length=20, description="计量单位")
    category: str = Field(..., max_length=20, description="类别")
    managed_class: ManagedClass = Field(default="stocked", description="共用类/车间单独需求类")
    code: str | None = Field(default=None, max_length=50, description="物料编码（采购编码表回填）")
    direct_dept: str | None = Field(default=None, max_length=100)
    inspect_class: str | None = Field(default=None, max_length=20)
    safety_stock: Decimal = Field(default=Decimal("0"), ge=0, description="安全库存量")
    max_stock: Decimal | None = Field(default=None, ge=0)
    monthly_demands: dict[str, Any] | None = Field(default=None, description="月需求 {部门: 量}")
    lead_time_days: int | None = Field(default=None, ge=0)
    secondary_holder: str | None = Field(default=None, max_length=100)
    no_expiry: bool | None = Field(default=None)
    remark: str | None = Field(default=None)


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    spec: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    category: str | None = Field(default=None, max_length=20)
    code: str | None = Field(default=None, max_length=50)
    direct_dept: str | None = Field(default=None, max_length=100)
    inspect_class: str | None = Field(default=None, max_length=20)
    safety_stock: Decimal | None = Field(default=None, ge=0)
    max_stock: Decimal | None = Field(default=None, ge=0)
    monthly_demands: dict[str, Any] | None = None
    lead_time_days: int | None = Field(default=None, ge=0)
    secondary_holder: str | None = Field(default=None, max_length=100)
    no_expiry: bool | None = None
    active: bool | None = None
    remark: str | None = None


class MaterialResponse(BaseModel):
    id: StrUUID
    code: str | None
    name: str
    spec: str | None
    unit: str
    category: str
    managed_class: str
    direct_dept: str | None
    inspect_class: str | None
    safety_stock: Decimal
    max_stock: Decimal | None
    monthly_demands: dict[str, Any] | None
    lead_time_days: int | None
    no_expiry: bool | None
    secondary_holder: str | None
    active: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class StockRowResponse(BaseModel):
    """库存总览行：available 为主数，on_hand/reserved 明细展开（设计 §三）。"""

    material: MaterialResponse
    on_hand: Decimal = Field(description="在手=Σ批次余额")
    reserved: Decimal = Field(description="预扣=Σ pending/approved 需料量")
    available: Decimal = Field(description="可用=on_hand-reserved")
    is_low: bool = Field(description="available < safety_stock 预警")
    low_gap: Decimal = Field(description="缺口=safety_stock-available（正数预警）")


class LotRowResponse(BaseModel):
    """物料批次（库存明细展开/FIFO 可视）。"""

    lot_id: StrUUID
    lot_no: str | None
    receipt_no: str | None
    arrived_at: datetime | None
    expiry_date: date | None
    location_code: str | None
    remaining_quantity: Decimal
    quantity: Decimal


class MaterialStockDetailResponse(BaseModel):
    stock: StockRowResponse
    lots: list[LotRowResponse]
    recent_movements: list[MovementResponse]


# ── 库位 ──


class LocationCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    zone: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)


class LocationResponse(BaseModel):
    id: StrUUID
    code: str
    zone: str
    description: str | None
    active: bool
    created_at: datetime


# ── 入库单（M2 OCR/manual 共用；此处先立契约）──


class ReceiptItemIn(BaseModel):
    material_id: StrUUID | None = Field(default=None, description="匹配到的主数据")
    name: str = Field(..., min_length=1, max_length=200)
    spec: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal = Field(..., gt=0)
    location_id: StrUUID | None = None
    expiry_date: date | None = None
    match_confidence: str | None = Field(default=None, description="匹配方式")
    match_score: Decimal | None = Field(default=None, description="置信度 0-100")
    unit_price: Decimal | None = None


class ReceiptCreate(BaseModel):
    """manual 兜底登记 / OCR 草稿落库共用契约（source 区分）。"""

    source: ReceiptSource = Field(description="ocr/manual/erp_import")
    mode: ManagedClass = Field(default="stocked")
    supplier_name: str | None = Field(default=None, max_length=200)
    delivery_note_no: str | None = Field(default=None, max_length=100)
    arrived_at: datetime | None = None
    target_dept: str | None = Field(default=None, max_length=100, description="direct 直发车间")
    erp_doc_no: str | None = Field(default=None, max_length=100)
    remark: str | None = None
    attachments: list[dict[str, Any]] | None = None
    items: list[ReceiptItemIn] = Field(..., min_length=1)

    @field_validator("target_dept")
    @classmethod
    def _target_dept_required_for_direct(cls, v, info):
        if info.data.get("mode") == "direct" and not v:
            raise ValueError("direct 车间单独需求类必须指定直发车间 target_dept")
        return v


class ReceiptAccept(BaseModel):
    """一屏确认：仓管员+使用部门经办双签（制度 5.2.2）。"""

    inspected_by_warehouse: str = Field(..., min_length=1, max_length=100, description="仓管员 open_id/姓名")
    inspected_by_dept: str = Field(..., min_length=1, max_length=100, description="使用部门经办人")
    inspect_checklist: dict[str, Any] | None = None
    items: list[ReceiptItemIn] | None = Field(
        default=None, description="修正后的行（人工修正低置信后提交；缺省用草稿原行）"
    )


class ReceiptReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReceiptItemResponse(BaseModel):
    id: StrUUID
    material_id: StrUUID | None
    material_name: str | None = None
    material_code: str | None = None
    name: str
    spec: str | None
    unit: str | None
    quantity: Decimal
    location_id: StrUUID | None
    lot_no: str | None
    expiry_date: date | None
    remaining_quantity: Decimal | None
    match_confidence: str | None
    match_score: Decimal | None
    unit_price: Decimal | None


class ReceiptResponse(BaseModel):
    id: StrUUID
    receipt_no: str
    source: str
    mode: str
    supplier_name: str | None
    delivery_note_no: str | None
    arrived_at: datetime | None
    target_dept: str | None
    status: str
    inspected_by_warehouse: str | None
    inspected_by_dept: str | None
    rejected_reason: str | None
    erp_doc_no: str | None
    ocr_result: dict[str, Any] | None
    inspect_checklist: dict[str, Any] | None
    attachments: list[Any] | None
    accepted_at: datetime | None
    remark: str | None
    created_at: datetime
    items: list[ReceiptItemResponse] = []


# ── 领用申请（M3；先立契约）──


class RequisitionItemIn(BaseModel):
    material_id: StrUUID
    need_qty: Decimal = Field(..., gt=0)


class RequisitionCreate(BaseModel):
    dept_name: str = Field(..., min_length=1, max_length=100)
    applicant: str = Field(..., min_length=1, max_length=100)
    applicant_open_id: str | None = Field(default=None, max_length=100)
    purpose: str | None = Field(default=None, max_length=500)
    req_type: RequisitionType = Field(default="normal")
    remark: str | None = None
    items: list[RequisitionItemIn] = Field(..., min_length=1)


class RequisitionSubmit(BaseModel):
    """提交审批：预扣生效，available 校验。"""


class RequisitionApprove(BaseModel):
    approver: str = Field(..., min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class RequisitionReject(BaseModel):
    approver: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=500)


class RequisitionIssueItem(BaseModel):
    item_id: StrUUID
    issued_qty: Decimal = Field(..., gt=0)


class RequisitionIssue(BaseModel):
    """发料确认：实发量（可改）+ FIFO 扣减 + 领用人点收。"""

    issued_by: str = Field(..., min_length=1, max_length=100)
    received_by: str = Field(..., min_length=1, max_length=100, description="领用人点收")
    items: list[RequisitionIssueItem] = Field(..., min_length=1)


class RequisitionItemResponse(BaseModel):
    id: StrUUID
    material_id: StrUUID
    material_name: str
    material_code: str | None
    spec: str | None
    unit: str | None
    need_qty: Decimal
    issued_qty: Decimal | None
    fifo_lot_allocations: list[Any] | None


class RequisitionResponse(BaseModel):
    id: StrUUID
    req_no: str
    dept_name: str
    applicant: str
    applicant_open_id: str | None
    purpose: str | None
    req_type: str
    status: str
    approval_channel: str | None
    approval_instance_code: str | None
    approval_status: str | None
    approval_note: str | None
    approved_by: str | None
    approved_at: datetime | None
    rejected_reason: str | None
    submitted_at: datetime | None
    issued_by: str | None
    issued_at: datetime | None
    received_by: str | None
    urgent_patch_deadline: datetime | None
    patched_at: datetime | None
    monthly_check: dict[str, Any] | None
    remark: str | None
    created_at: datetime
    items: list[RequisitionItemResponse] = []


# ── 流水 ──


class MovementResponse(BaseModel):
    id: StrUUID
    movement_no: str
    direction: str
    business_type: str
    material_id: StrUUID | None
    material_name: str
    spec: str | None
    unit: str | None
    lot_no: str | None
    quantity: Decimal
    occurred_at: datetime
    operator: str | None
    dept_name: str | None
    ref_table: str | None
    ref_id: StrUUID | None
    erp_status: str
    erp_entered_at: datetime | None
    remark: str | None


class MovementErpMark(BaseModel):
    """仓管员/车间在 ERP 录完后批量点「已录入」（月度对账口径）。"""

    movement_ids: list[StrUUID] = Field(..., min_length=1)
    erp_operator: str | None = Field(default=None, max_length=100)


class ImportStatsResponse(BaseModel):
    """清单/编码表导入统计。"""

    total_rows: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class CodeBackfillStatsResponse(BaseModel):
    """编码表回填统计（P2 定案通道）。"""

    total_rows: int
    matched: int
    backfilled: int
    new_materials: int
    errors: list[str] = Field(default_factory=list)


# ── 盘点（二期 M4）──


class StocktakeCreate(BaseModel):
    take_type: StocktakeType = Field(default="monthly", description="calibration=期初校准（P4）")
    note: str | None = None


class StocktakeItemFill(BaseModel):
    """手机实盘直填：填数即算差异。"""

    actual_qty: Decimal = Field(..., ge=0)
    explanation: str | None = Field(default=None, max_length=500)


class StocktakeReview(BaseModel):
    explained_by: str = Field(..., min_length=1, max_length=100)
    note: str | None = None


class StocktakeConfirm(BaseModel):
    """Web 确认门：人确认才入账（AI 永不自动动账红线）。"""

    confirmed_by: str = Field(..., min_length=1, max_length=100)


class StocktakeItemResponse(BaseModel):
    id: StrUUID
    material_id: StrUUID
    code: str | None
    name: str
    spec: str | None
    unit: str | None
    unit_price: Decimal | None
    book_qty: Decimal
    actual_qty: Decimal | None
    diff_qty: Decimal | None
    diff_amount: Decimal | None
    explanation: str | None


class StocktakeResponse(BaseModel):
    id: StrUUID
    take_no: str
    take_type: str
    status: str
    snapshot_at: datetime | None
    summary_note: str | None
    diff_surplus_items: int | None
    diff_deficit_items: int | None
    diff_total_amount: Decimal | None
    explained_by: str | None
    explained_at: datetime | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    remark: str | None
    created_at: datetime


# ── 退库（二期 M4）──


class ReturnItemIn(BaseModel):
    material_id: StrUUID
    quantity: Decimal = Field(..., gt=0)
    preferred_lot_id: StrUUID | None = Field(
        default=None, description="优先回原批次；无效则新建 return 批次"
    )


class ReturnCreate(BaseModel):
    dept_name: str = Field(..., min_length=1, max_length=100)
    returned_by: str = Field(..., min_length=1, max_length=100)
    returned_by_open_id: str | None = Field(default=None, max_length=100)
    remark: str | None = None
    items: list[ReturnItemIn] = Field(..., min_length=1)


class ReturnSign(BaseModel):
    leader: str = Field(..., min_length=1, max_length=100)


class ReturnAcceptBody(BaseModel):
    accepted_by: str = Field(..., min_length=1, max_length=100)


class ReturnReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReturnResponse(BaseModel):
    id: StrUUID
    return_no: str
    dept_name: str
    returned_by: str
    items: list[dict[str, Any]]
    leader_signed: bool
    leader_signed_by: str | None
    leader_signed_at: datetime | None
    status: str
    accepted_by: str | None
    accepted_at: datetime | None
    rejected_reason: str | None
    lot_adjustments: list[dict[str, Any]] | None
    remark: str | None
    created_at: datetime
