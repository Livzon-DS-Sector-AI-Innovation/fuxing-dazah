"""五金库 request/response schemas（warehouse.hardware）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator

from pydantic import BaseModel, ConfigDict, Field, model_validator

StrUUID = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else v)]


class ORMResponse(BaseModel):
    """响应模型基类：允许从 ORM 对象直接 model_validate（from_attributes）。"""

    model_config = ConfigDict(from_attributes=True)


ManagedClass = Literal["stocked", "direct"]
ReceiptSource = Literal["ocr", "manual", "excel", "erp_import", "stocktake", "return"]
ReceiptStatus = Literal["draft", "accepted", "rejected"]
RequisitionType = Literal["normal", "urgent", "excess"]
RequisitionStatus = Literal[
    "draft", "pending", "approved", "issued", "rejected", "cancelled"
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
    location_no: str | None = Field(
        default=None, max_length=100, description="位号（默认存放位，目录级）"
    )
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
    location_no: str | None = Field(default=None, max_length=100)
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


class MaterialResponse(ORMResponse):
    id: StrUUID
    code: str | None
    name: str
    spec: str | None
    unit: str
    category: str
    location_no: str | None
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


class StockRowResponse(ORMResponse):
    """库存总览行：available 为主数，on_hand/reserved 明细展开（设计 §三）。"""

    material: MaterialResponse
    on_hand: Decimal = Field(description="在手=Σ批次余额")
    reserved: Decimal = Field(description="预扣=Σ pending/approved 需料量")
    available: Decimal = Field(description="可用=on_hand-reserved")
    is_low: bool = Field(description="available < safety_stock 预警")
    low_gap: Decimal = Field(description="缺口=safety_stock-available（正数预警）")


class LotRowResponse(ORMResponse):
    """物料批次（库存明细展开/FIFO 可视）。"""

    lot_id: StrUUID
    lot_no: str | None
    receipt_no: str | None
    arrived_at: datetime | None
    expiry_date: date | None
    location_code: str | None
    remaining_quantity: Decimal
    quantity: Decimal


class MaterialStockDetailResponse(ORMResponse):
    stock: StockRowResponse
    lots: list[LotRowResponse]
    recent_movements: list[MovementResponse]


# ── 库位 ──


class LocationCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    zone: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)


class LocationResponse(ORMResponse):
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
    target_dept: str | None = Field(
        default=None,
        max_length=100,
        description="direct 直发车间（草稿可空——OCR 识别不到部门线索时由仓管员确认时补；accept 侧强制）",
    )
    erp_doc_no: str | None = Field(default=None, max_length=100)
    remark: str | None = None
    attachments: list[dict[str, Any]] | None = None
    items: list[ReceiptItemIn] = Field(..., min_length=1)
    ocr_result: dict[str, Any] | None = Field(
        default=None,
        description="截图解析留痕原样回传（已退役保留兼容；纯手动登记为 None）",
    )
    excel_result: dict[str, Any] | None = Field(
        default=None,
        description="Excel 解析留痕原样回传（方式②：excel/parse 返回的 excel_result 提交时带回）",
    )


class ReceiptParseItem(ReceiptItemIn):
    """截图解析行（方式2）：在 ReceiptItemIn 上加匹配标记（前端标黄/标红依据）。"""

    matched_name: str | None = Field(default=None, description="匹配到的主数据名称（null=未匹配）")
    low_confidence: bool = Field(default=False, description="低置信行（前端标黄人工核对）")
    managed_class: str | None = Field(
        default=None, description="匹配物料的两类归属 stocked/direct（未匹配为 null；前端按单分 mode 用）"
    )


class ReceiptParseDocument(BaseModel):
    """按「入库单号」分组的单据摘要（2026-11-20 拍板：Web 端与机器人通道同口径分单）。

    item_indexes 指向 items[] 下标（分组模板；行匹配状态由前端实时重算）。
    """

    key: str = Field(description="分组键=入库单号原文（空串=无单号组）")
    delivery_note_no: str | None = Field(default=None, description="入库单号（null=无单号）")
    supplier_name: str | None = None
    item_indexes: list[int]
    stocked_count: int = 0
    direct_count: int = 0
    unmatched_count: int = 0
    all_matched: bool = True
    mode: str = Field(description="stocked/direct（有 stocked 物料行=stocked，否则 direct）")


class ReceiptParseResponse(BaseModel):
    """POST /receipts/excel/parse 响应：纯解析不落库，表单预填契约。

    预填后人工核对修正走 POST /receipts（source=excel + excel_result 回传）。
    """

    mode: str = Field(description="stocked/direct（单头 mode 预判）")
    supplier_name: str | None = None
    delivery_note_no: str | None = None
    remark: str | None = None
    target_dept: str | None = Field(default=None, description="direct 模式下从备注猜的直发车间")
    items: list[ReceiptParseItem]
    documents: list[ReceiptParseDocument] = Field(
        default_factory=list,
        description="按入库单号分组的单据摘要（多单文件分栏处理；旧客户端可忽略）",
    )
    match_summary: list[dict[str, Any]] = Field(default_factory=list)
    matched_stocked: int = 0
    matched_direct: int = 0
    unmatched: int = 0
    errors: list[dict[str, Any]] = Field(
        default_factory=list, description="逐行解析告警 [{row, name, reason}]（不阻断其余行）"
    )
    excel_result: dict[str, Any] | None = Field(
        default=None, description="Excel 解析留痕——表单提交时随 ReceiptCreate.excel_result 原样回传"
    )
    ocr_result: dict[str, Any] | None = Field(
        default=None, description="（兼容字段，Excel 方式恒 None；截图解析已退役）"
    )


class ReceiptAccept(BaseModel):
    """确认入账：仓管员审核确认入库（2026-11-20 起取消使用部门经办人双签）。"""

    inspected_by_warehouse: str = Field(..., min_length=1, max_length=100, description="仓管员 open_id/姓名")
    inspected_by_dept: str | None = Field(
        default=None,
        max_length=100,
        description="使用部门经办人（可选；前端已取消双签，仅 Agent/自动入账通道回填留痕）",
    )
    inspect_checklist: dict[str, Any] | None = None
    items: list[ReceiptItemIn] | None = Field(
        default=None, description="修正后的行（人工修正低置信后提交；缺省用草稿原行）"
    )


class ReceiptReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReceiptItemResponse(ORMResponse):
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
    photo_screening: dict[str, Any] | None = None  # M7 实物照片初筛（advisory）


class ReceiptResponse(ORMResponse):
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
    erp_imported_at: datetime | None = None
    reconcile_status: str = "none"  # M8 对账轴
    matched_receipt_id: StrUUID | None = None
    auto_accepted: bool = False  # M9 自动入账标记
    auto_accept_snapshot: dict[str, Any] | None = None
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
    approver_user_id: str | None = Field(
        default=None, max_length=100, description="指定审批人飞书 user_id（发起人自选节点）"
    )
    approver_name: str | None = Field(default=None, max_length=100, description="指定审批人姓名")
    purpose: str | None = Field(default=None, max_length=500)
    req_type: RequisitionType = Field(default="normal")
    urgent_reason: str | None = Field(
        default=None, max_length=200, description="紧急原因（req_type=urgent 必填）"
    )
    remark: str | None = None
    items: list[RequisitionItemIn] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _urgent_reason_required(self) -> "RequisitionCreate":
        if self.req_type == "urgent" and not (self.urgent_reason or "").strip():
            raise ValueError("紧急申领必须填写紧急原因")
        return self


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


class RequisitionItemResponse(ORMResponse):
    id: StrUUID
    material_id: StrUUID
    material_name: str
    material_code: str | None
    spec: str | None
    unit: str | None
    need_qty: Decimal
    issued_qty: Decimal | None
    fifo_lot_allocations: list[Any] | None


class RequisitionResponse(ORMResponse):
    id: StrUUID
    req_no: str
    dept_name: str
    applicant: str
    applicant_open_id: str | None
    approver_user_id: str | None = None
    approver_name: str | None = None
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
    urgent_reason: str | None = None
    monthly_check: dict[str, Any] | None
    remark: str | None
    created_at: datetime
    items: list[RequisitionItemResponse] = []


# ── 流水 ──


class MovementResponse(ORMResponse):
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


class ImportStatsResponse(ORMResponse):
    """清单/编码表导入统计。"""

    total_rows: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class CodeBackfillStatsResponse(ORMResponse):
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


class StocktakeItemResponse(ORMResponse):
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


class StocktakeResponse(ORMResponse):
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


class ReturnFromRequisitionCreate(BaseModel):
    """从已发料领料单发起退料（2026-11-26）：提交即发起审批（额度校验双卡点）。"""

    requisition_id: StrUUID
    returned_by: str = Field(default="", max_length=100, description="留空=取领料单申请人")
    approver_user_id: str | None = Field(
        default=None, max_length=100, description="指定审批人飞书 user_id（主管及以上）"
    )
    approver_name: str | None = Field(default=None, max_length=100)
    reason_note: str | None = Field(default=None, max_length=500)
    items: list[ReturnItemIn] = Field(..., min_length=1)


class ReturnSign(BaseModel):
    leader: str = Field(..., min_length=1, max_length=100)


class ReturnAcceptBody(BaseModel):
    accepted_by: str = Field(default="web", max_length=100)


class ReturnReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReturnResponse(ORMResponse):
    id: StrUUID
    return_no: str
    requisition_id: StrUUID | None
    requisition_instance_code: str | None
    approver_user_id: str | None
    approver_name: str | None
    approval_channel: str | None
    approval_instance_code: str | None
    approval_status: str | None
    dept_name: str
    returned_by: str
    items: list[dict[str, Any]]
    leader_signed: bool
    leader_signed_by: str | None
    leader_signed_at: datetime | None
    status: str
    accepted_by: str | None
    accepted_at: datetime | None
    rejected_by: str | None
    rejected_reason: str | None
    lot_adjustments: list[dict[str, Any]] | None
    remark: str | None
    created_at: datetime
    can_approve: bool = Field(
        default=False, description="当前用户能否在平台点通过/驳回（退料管理权限或所选审批人）"
    )


# ── 月度采购计划（二期 M5）──


class PlanGenerate(BaseModel):
    """手动生成/重跑计划草案（25 日任务同款入口；同月幂等）。"""

    plan_month: str | None = Field(
        default=None, description="缺省=次月（YYYY-MM）", pattern=r"^\d{4}-\d{2}$"
    )
    annotate: bool = Field(default=True, description="是否跑 AI 用量注释")


class PlanItemUpdate(BaseModel):
    """人工编辑草案行（→ is_edited，同月重跑保留人工值）。"""

    purchase_qty: Decimal | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=500)
    ai_note: str | None = Field(default=None, max_length=500, description="采纳注释时可改写")


class PlanItemResponse(ORMResponse):
    id: StrUUID
    material_id: StrUUID
    code: str | None
    name: str
    spec: str | None
    unit: str | None
    monthly_demand_total: Decimal
    safety_stock: Decimal
    stock_on_25th: Decimal
    monthly_usage: Decimal
    purchase_qty: Decimal
    ai_note: str | None
    is_edited: bool
    remark: str | None


class PlanResponse(ORMResponse):
    id: StrUUID
    plan_month: str
    status: str
    snapshot_at: datetime | None
    usage_window_days: int
    annotated: bool
    exported_at: datetime | None
    remark: str | None
    created_at: datetime


# ── 温湿度日检（二期 M5）──


class EnvLogUpsert(BaseModel):
    log_date: date
    temperature: Decimal | None = Field(default=None, ge=-50, le=80)
    humidity: Decimal | None = Field(default=None, ge=0, le=100)
    checked_by: str | None = Field(default=None, max_length=100)
    abnormal_note: str | None = Field(default=None, max_length=500)


class EnvLogResponse(ORMResponse):
    id: StrUUID
    log_date: date
    temperature: Decimal | None
    humidity: Decimal | None
    checked_by: str | None
    abnormal_note: str | None


# ── 报废（三期 M7）──


class ScrapItemIn(BaseModel):
    material_id: StrUUID
    quantity: Decimal = Field(..., gt=0)
    preferred_lot_id: StrUUID | None = Field(
        default=None, description="指定批次（可选；空=FIFO 自动扣）"
    )


class ScrapCreate(BaseModel):
    dept_name: str = Field(..., min_length=1, max_length=100)
    requested_by: str = Field(..., min_length=1, max_length=100)
    requested_by_open_id: str | None = Field(default=None, max_length=100)
    approver_user_id: str | None = Field(
        default=None, max_length=100,
        description="指定审批人飞书 user_id（主管及以上，发起人自选）",
    )
    approver_name: str | None = Field(default=None, max_length=100)
    scrap_reason: str = Field(
        ..., description="报废条件（制度5.6）：expired/damaged/obsolete/appraisal"
    )
    reason_note: str | None = Field(default=None, max_length=500)
    attachments: list[dict[str, Any]] | None = None
    remark: str | None = None
    items: list[ScrapItemIn] = Field(..., min_length=1)


class ScrapApprove(BaseModel):
    approved_by: str = Field(default="", max_length=100, description="留空=取当前登录用户姓名")


class ScrapExecute(BaseModel):
    executed_by: str = Field(..., min_length=1, max_length=100)


class ScrapReject(BaseModel):
    rejected_by: str = Field(default="", max_length=100, description="留空=取当前登录用户姓名")
    reason: str = Field(..., min_length=1, max_length=500)


class ScrapItemResponse(ORMResponse):
    id: StrUUID
    material_id: StrUUID
    quantity: Decimal
    preferred_lot_id: StrUUID | None
    name: str
    spec: str | None
    unit: str | None
    unit_price: Decimal | None


class ScrapResponse(ORMResponse):
    id: StrUUID
    scrap_no: str
    dept_name: str
    requested_by: str
    scrap_reason: str
    reason_note: str | None
    attachments: list[dict[str, Any]] | None
    approver_user_id: str | None
    approver_name: str | None
    approval_channel: str | None
    approval_instance_code: str | None
    approval_status: str | None
    dept_confirmed_by: str | None
    dept_confirmed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    executed_by: str | None
    rejected_by: str | None
    rejected_reason: str | None
    status: str
    scrapped_at: datetime | None
    lot_allocations: list[dict[str, Any]] | None
    remark: str | None
    created_at: datetime
    items: list[ScrapItemResponse] = Field(default_factory=list)
    can_approve: bool = Field(
        default=False, description="当前用户能否在平台点通过/驳回（报废管理权限或所选审批人）"
    )


class PhotoScreeningBody(BaseModel):
    """实物照片初筛请求（Web 工作台/agent 两入口同构）。"""

    photos: list[dict[str, Any]] = Field(..., min_length=1)
    operator: str | None = Field(default=None, max_length=100)
