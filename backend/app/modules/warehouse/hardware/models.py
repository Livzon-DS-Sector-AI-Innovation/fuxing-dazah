"""五金库 ORM 模型（一期 7 张核心表 + 二期 5 张表，设计文档 §二/§2.6）。

schema=warehouse、表名前缀 hardware_。数量精度统一 Numeric(18,3)；
时区 Asia/Shanghai（DateTime(timezone=True)）；movement.quantity 恒正、
direction 表方向。库存变动收口：只随入库单 accepted 与出库单 issued；
盘点调整（stocktake_adj）/退库（return_in）以独立单据类型另列（二期）。

⚠️ 本文件是 warehouse 模块的子包 models，warehouse 顶层 models.py 不会
带出这些表——backend/alembic/env.py 模型发现清单已显式 import。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

# ── 受控枚举（模块级常量；DB 层用 CheckConstraint 固化）──

# 类别：清单 7 大类 + direct 沉淀类（设计 §2.1）
HARDWARE_CATEGORIES = (
    "金属管道",
    "金属管件",
    "金属阀门",
    "食品级垫片",
    "金属轴承",
    "UPVC管件",
    "ABS管件",
    "仪器仪表",
    "化玻试剂",
    "劳保用品",
    "耗材",
    "其他",
)
MANAGED_CLASSES = ("stocked", "direct")  # 共用类（清单内，占库存）/ 车间单独需求类（不占库存）
# ERP 变故后主通道=ocr（口径13）；stocktake/return=二期系统单据载体（盘点盘盈
# 入账批次、退库回加批次——独立单据类型另列，不冒充采购入库）
RECEIPT_SOURCES = ("ocr", "manual", "erp_import", "stocktake", "return")
RECEIPT_STATUSES = ("draft", "accepted", "rejected")
MATCH_METHODS = ("erp_code", "name_spec", "synonym", "manual", "unmatched")
REQUISITION_TYPES = ("normal", "urgent", "excess")
REQUISITION_STATUSES = (
    "draft",
    "pending",
    "approved",
    "issued",
    "rejected",
    "cancelled",
    "overdue_unpatched",
)
MOVEMENT_DIRECTIONS = ("inbound", "outbound", "adjust")
MOVEMENT_BUSINESS_TYPES = (
    "receipt",
    "pass_in",
    "pass_out",
    "req_issue",
    "urgent_issue",
    "return_in",
    "stocktake_adj",
    "scrap",
)
ERP_STATUSES = ("pending", "entered")

# 月需求 5 部门（清单列头；monthly_demands JSON 的键域）
DEMAND_DEPARTMENTS = ("发酵", "提炼一期", "提炼二期", "精制机修", "动力机修")

_QTY = Numeric(18, 3)


class HardwareMaterial(BaseModel):
    """五金库物料主数据：共用类（清单 492 项）全量权威 + direct 类常用沉淀。

    code=采购 ERP 编码（P2 定案不自造），清单导入留空、编码表到位后回填。
    """

    __tablename__ = "hardware_materials"
    __table_args__ = (
        # code 允许 NULL（清单导入留空）；有值时唯一（软删除外）
        Index(
            "uq_hardware_materials_code",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL AND is_deleted = false"),
        ),
        Index(
            "uq_hardware_materials_name_spec",
            "name",
            "spec",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "managed_class IN ('stocked', 'direct')",
            name="ck_hardware_materials_managed_class",
        ),
        CheckConstraint("safety_stock >= 0", name="ck_hardware_materials_safety_stock"),
        {"schema": "warehouse"},
    )

    code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="物料编码（采购 ERP 编码，导入时留空待回填）"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物资名称")
    spec: Mapped[str | None] = mapped_column(String(200), comment="规格型号")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="计量单位")
    category: Mapped[str] = mapped_column(String(20), nullable=False, comment="类别（7 大类+沉淀类）")
    managed_class: Mapped[str] = mapped_column(
        String(10), nullable=False, default="stocked", server_default="stocked",
        comment="stocked 共用类占库存 / direct 车间单独需求类不占库存",
    )
    direct_dept: Mapped[str | None] = mapped_column(
        String(100), comment="direct 专属物资所属车间"
    )
    inspect_class: Mapped[str | None] = mapped_column(
        String(20), comment="验收类别：五金备件/仪器仪表/电器元件/化玻试剂/劳保用品/耗材"
    )
    safety_stock: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="安全库存量（available 低于即预警）",
    )
    max_stock: Mapped[Decimal | None] = mapped_column(_QTY, comment="最大库存")
    monthly_demands: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="月需求 JSON：{部门: 量}（发酵/提炼一期/提炼二期/精制机修/动力机修）"
    )
    lead_time_days: Mapped[int | None] = mapped_column(Integer, comment="采购周期（天）")
    shelf_life_months: Mapped[int | None] = mapped_column(Integer, comment="效期（月）")
    no_expiry: Mapped[bool | None] = mapped_column(
        Boolean, comment="无效期（五金件默认）"
    )
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), comment="最近入库单价（盘点差异金额用）"
    )
    secondary_holder: Mapped[str | None] = mapped_column(
        String(100), comment="二级库归属车间标注（P6：一期不管，台账级）"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="启用"
    )
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")


class HardwareLocation(BaseModel):
    """五金库库位：区域-架-层（平台下大件 / 平台上货架）。"""

    __tablename__ = "hardware_locations"
    __table_args__ = (
        Index(
            "uq_hardware_locations_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="库位编码，如 P-A-03（平台下A区3位）"
    )
    zone: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="区域：平台下/平台上货架"
    )
    description: Mapped[str | None] = mapped_column(String(200), comment="说明")
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class HardwareReceipt(BaseModel):
    """五金库入库单头：OCR 采集（主）/ manual 兜底 / erp_import 预留。

    状态机：draft（草稿不动库存）→ accepted（入账）/ rejected（拒收留证）。
    """

    __tablename__ = "hardware_receipts"
    __table_args__ = (
        Index(
            "uq_hardware_receipts_no",
            "receipt_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_hardware_receipts_erp_doc",
            "erp_doc_no",
            unique=True,
            postgresql_where=text("erp_doc_no IS NOT NULL AND is_deleted = false"),
        ),
        CheckConstraint(
            "source IN ('ocr', 'manual', 'erp_import')",
            name="ck_hardware_receipts_source",
        ),
        CheckConstraint(
            "status IN ('draft', 'accepted', 'rejected')",
            name="ck_hardware_receipts_status",
        ),
        CheckConstraint(
            "mode IN ('stocked', 'direct')",
            name="ck_hardware_receipts_mode",
        ),
        {"schema": "warehouse"},
    )

    receipt_no: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="入库单号 WJK-RK-YYMMDD-序号"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="数据源：ocr 主通道 / manual 兜底 / erp_import 预留"
    )
    erp_doc_no: Mapped[str | None] = mapped_column(
        String(100), comment="ERP 单据号（仅 erp_import 通道，导入去重键）"
    )
    erp_imported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="ERP 导入时间"
    )
    supplier_name: Mapped[str | None] = mapped_column(String(200), comment="供应商")
    delivery_note_no: Mapped[str | None] = mapped_column(
        String(100), comment="厂家送货单号"
    )
    arrived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="到货日期"
    )
    target_dept: Mapped[str | None] = mapped_column(
        String(100), comment="direct 类直发领用车间"
    )
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="stocked", server_default="stocked",
        comment="stocked 实际入库 / direct 出入双流水净零",
    )
    inspected_by_warehouse: Mapped[str | None] = mapped_column(
        String(100), comment="验收确认·仓管员（open_id）"
    )
    inspected_by_dept: Mapped[str | None] = mapped_column(
        String(100), comment="验收确认·使用部门经办人（open_id，制度 5.2.2 双人验收）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
        comment="draft 草稿不动库存 / accepted 确认入账 / rejected 拒收退供应商",
    )
    rejected_reason: Mapped[str | None] = mapped_column(
        String(500), comment="拒收原因（留证）"
    )
    ocr_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        comment="OCR 结构化提取结果：供应商/单号/日期/多行品名规格数量+逐行匹配置信度",
    )
    inspect_checklist: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="按 inspect_class 模板的线下物理检查勾选"
    )
    attachments: Mapped[list[Any] | None] = mapped_column(
        JSONB, comment="附件：送货单照片/合格证/材质证明 file tokens"
    )
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), comment="整单参考单价（ERP 带出）"
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="确认入账时间"
    )
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")


class HardwareReceiptItem(BaseModel):
    """五金库入库明细行：每行=一个入库批次（lot），FIFO 扣减基础。

    direct 类行 material_id 可空（自由文本 name/spec/unit）；
    remaining_quantity 仅 stocked 有值（初始=quantity，发料按批扣减）。
    """

    __tablename__ = "hardware_receipt_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_hardware_receipt_items_qty"),
        CheckConstraint(
            "remaining_quantity IS NULL OR remaining_quantity >= 0",
            name="ck_hardware_receipt_items_remaining",
        ),
        Index("ix_hardware_receipt_items_material", "material_id"),
        Index("ix_hardware_receipt_items_receipt", "receipt_id"),
        {"schema": "warehouse"},
    )

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_receipts.id"),
        nullable=False,
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_materials.id"),
        comment="主数据匹配结果；direct 未匹配时 NULL",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="品名（OCR/自由文本）")
    spec: Mapped[str | None] = mapped_column(String(200), comment="规格型号")
    unit: Mapped[str | None] = mapped_column(String(20), comment="单位")
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False, comment="入库数量")
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_locations.id"),
        comment="库位（仅 stocked，上架）",
    )
    lot_no: Mapped[str | None] = mapped_column(
        String(50), comment="批次号=本行 id 生成（仅 stocked）"
    )
    arrived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="到货时间冗余（FIFO 排序键，随单头）"
    )
    expiry_date: Mapped[date | None] = mapped_column(Date, comment="效期")
    remaining_quantity: Mapped[Decimal | None] = mapped_column(
        _QTY, comment="批次剩余量（FIFO 扣减余额，仅 stocked）"
    )
    match_confidence: Mapped[str | None] = mapped_column(
        String(20),
        comment="匹配方式：erp_code 精确/name_spec 模糊/synonym 同义词/manual 人工/unmatched",
    )
    match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), comment="匹配置信度 0-100（低于阈值标黄只标记不代改）"
    )
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), comment="行单价（回写主数据最近单价）"
    )


class HardwareRequisition(BaseModel):
    """五金库领用申请单头（共用类 stocked 唯一需审批开单的出库）。

    状态机：draft → pending（提审批+预扣）→ approved（预扣保持）→
    issued（实扣）/ rejected（释放）/ cancelled；urgent 发料后 24h 未补单
    → overdue_unpatched。
    """

    __tablename__ = "hardware_requisitions"
    __table_args__ = (
        Index(
            "uq_hardware_requisitions_no",
            "req_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "req_type IN ('normal', 'urgent', 'excess')",
            name="ck_hardware_requisitions_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'issued', 'rejected',"
            " 'cancelled', 'overdue_unpatched')",
            name="ck_hardware_requisitions_status",
        ),
        Index("ix_hardware_requisitions_status", "status"),
        Index("ix_hardware_requisitions_dept", "dept_name"),
        {"schema": "warehouse"},
    )

    req_no: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="领料单号 WJK-LY-YYMMDD-序号"
    )
    dept_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="领用部门")
    applicant: Mapped[str] = mapped_column(String(100), nullable=False, comment="领用人姓名")
    applicant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("identity.users.id"),
        comment="identity 用户",
    )
    applicant_open_id: Mapped[str | None] = mapped_column(
        String(100), comment="领用人飞书 open_id（通知用）"
    )
    purpose: Mapped[str | None] = mapped_column(String(500), comment="用途")
    req_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="normal", server_default="normal",
        comment="normal 常规 / urgent 紧急（先发后补）/ excess 超额",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    approval_channel: Mapped[str | None] = mapped_column(
        String(10), comment="审批通道：feishu / manual（状态机对通道无感）"
    )
    approval_instance_code: Mapped[str | None] = mapped_column(
        String(100), comment="飞书审批实例 code（feishu 通道）"
    )
    approval_status: Mapped[str | None] = mapped_column(
        String(20), comment="审批结果映射：approved/rejected/cancelled"
    )
    approval_note: Mapped[str | None] = mapped_column(
        Text, comment="审批备注（manual 通道代录结论；超额=需生产总监提示）"
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), comment="审批人")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="提交审批时间（预扣生效）"
    )
    issued_by: Mapped[str | None] = mapped_column(String(100), comment="发料仓管员")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="发料时间")
    received_by: Mapped[str | None] = mapped_column(String(100), comment="领用人点收（=签收）")
    urgent_patch_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="紧急单补审批截止（发料时间+24h）"
    )
    patched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="紧急单补审批完成时间"
    )
    monthly_check: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="提交时该部门当月已领量 vs 月需求快照（领用标准核对支撑）"
    )
    remark: Mapped[str | None] = mapped_column(Text)


class HardwareRequisitionItem(BaseModel):
    """领用明细行：需料量 need_qty（预扣口径）/ 实发量 issued_qty（发料时可改）。"""

    __tablename__ = "hardware_requisition_items"
    __table_args__ = (
        CheckConstraint("need_qty > 0", name="ck_hardware_req_items_need"),
        CheckConstraint(
            "issued_qty IS NULL OR issued_qty >= 0",
            name="ck_hardware_req_items_issued",
        ),
        Index("ix_hardware_req_items_req", "requisition_id"),
        Index("ix_hardware_req_items_material", "material_id"),
        {"schema": "warehouse"},
    )

    requisition_id: Mapped[uuid.UUID] = mapped_column(  # noqa: UP037
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_requisitions.id"),
        nullable=False,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(  # noqa: UP037
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_materials.id"),
        nullable=False,
        comment="领料必选主数据（共用类）",
    )
    need_qty: Mapped[Decimal] = mapped_column(_QTY, nullable=False, comment="需料量")
    issued_qty: Mapped[Decimal | None] = mapped_column(
        _QTY, comment="实发量（发料确认时可改）"
    )
    fifo_lot_allocations: Mapped[list[Any] | None] = mapped_column(
        JSONB, comment="FIFO 批次分配建议/实际 [{lot_no, location, qty}]"
    )


class HardwareMovement(BaseModel):
    """五金库出入库流水（append-only，ERP 核对载体）。

    quantity 恒正、direction 表方向；库存变动只随入库 accepted 与出库
    issued 发生（收口原则），direct 类出入双流水净零。
    """

    __tablename__ = "hardware_movements"
    __table_args__ = (
        Index(
            "uq_hardware_movements_no",
            "movement_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint("quantity > 0", name="ck_hardware_movements_qty"),
        CheckConstraint(
            "direction IN ('inbound', 'outbound', 'adjust')",
            name="ck_hardware_movements_direction",
        ),
        CheckConstraint(
            "business_type IN ('receipt', 'pass_in', 'pass_out', 'req_issue',"
            " 'urgent_issue', 'return_in', 'stocktake_adj', 'scrap')",
            name="ck_hardware_movements_biz_type",
        ),
        CheckConstraint(
            "erp_status IN ('pending', 'entered')",
            name="ck_hardware_movements_erp_status",
        ),
        Index("ix_hardware_movements_material", "material_id"),
        Index("ix_hardware_movements_occurred", "occurred_at"),
        Index("ix_hardware_movements_business", "business_type"),
        {"schema": "warehouse"},
    )

    movement_no: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="流水号"
    )
    direction: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="inbound/outbound/adjust"
    )
    business_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="receipt/pass_in/pass_out/req_issue/urgent_issue/return_in/stocktake_adj/scrap"
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_materials.id"),
        comment="主数据；direct 自由文本未匹配时 NULL",
    )
    material_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="品名快照（台账直读）"
    )
    spec: Mapped[str | None] = mapped_column(String(200), comment="规格快照")
    unit: Mapped[str | None] = mapped_column(String(20), comment="单位快照")
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_receipt_items.id"),
        comment="入库批次行（FIFO 扣减对应）",
    )
    lot_no: Mapped[str | None] = mapped_column(String(50), comment="批次号快照")
    quantity: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, comment="数量（恒正，方向看 direction）"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="发生时间"
    )
    operator: Mapped[str | None] = mapped_column(String(100), comment="经办人")
    dept_name: Mapped[str | None] = mapped_column(
        String(100), comment="关联部门（direct 直发/领用部门）"
    )
    ref_table: Mapped[str | None] = mapped_column(
        String(50), comment="来源单据表：hardware_receipts/hardware_requisitions/…"
    )
    ref_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), comment="来源单据 id"
    )
    erp_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default="pending",
        comment="ERP 录入标记：pending 未录 / entered 已录（一期人工点，月度对账）",
    )
    erp_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erp_operator: Mapped[str | None] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(500))


# ── 二期表（设计 §2.6）──

STOCKTAKE_TYPES = ("monthly", "annual", "special", "calibration")
STOCKTAKE_STATUSES = ("draft", "counting", "reviewed", "confirmed", "cancelled")
RETURN_STATUSES = ("draft", "accepted", "rejected")
PLAN_STATUSES = ("draft", "exported")


class HardwareStocktake(BaseModel):
    """五金库盘点单（设计 §2.6）：book 快照 vs 实盘直填 → 差异 → 人确认才入账。

    状态机：draft（生成=快照）→ counting（首行实盘）→ reviewed（差异说明齐、
    待负责人确认）→ confirmed（ADJ 入账，唯一动账点）/ cancelled（确认前作废）。
    take_type=calibration 为期初校准（P4：零库存起步后首次全面盘盈入账）。
    """

    __tablename__ = "hardware_stocktakes"
    __table_args__ = (
        Index(
            "uq_hardware_stocktakes_no",
            "take_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "take_type IN ('monthly', 'annual', 'special', 'calibration')",
            name="ck_hardware_stocktakes_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'counting', 'reviewed', 'confirmed', 'cancelled')",
            name="ck_hardware_stocktakes_status",
        ),
        Index("ix_hardware_stocktakes_status", "status"),
        {"schema": "warehouse"},
    )

    take_no: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="盘点单号 WJK-PD-YYMMDD-序号"
    )
    take_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="monthly", server_default="monthly",
        comment="monthly 月度/annual 年度/special 专项/calibration 期初校准（P4）",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
        comment="draft 快照/counting 实盘/reviewed 待确认/confirmed 已入账/cancelled",
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="book 快照时间"
    )
    summary_note: Mapped[str | None] = mapped_column(
        Text, comment="盘点总结说明（差异汇总口径）"
    )
    diff_surplus_items: Mapped[int | None] = mapped_column(
        Integer, comment="盘盈行数（确认时回写）"
    )
    diff_deficit_items: Mapped[int | None] = mapped_column(
        Integer, comment="盘亏行数（确认时回写）"
    )
    diff_total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), comment="差异金额合计（确认时回写）"
    )
    explained_by: Mapped[str | None] = mapped_column(
        String(100), comment="差异说明填写人"
    )
    explained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(
        String(100), comment="确认人（Web 确认门，人确认才入账）"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)


class HardwareStocktakeItem(BaseModel):
    """盘点明细行：每 active stocked 物料一行（book/actual/diff 快照冗余主数据）。"""

    __tablename__ = "hardware_stocktake_items"
    __table_args__ = (
        CheckConstraint("book_qty >= 0", name="ck_hardware_stocktake_items_book"),
        CheckConstraint(
            "actual_qty IS NULL OR actual_qty >= 0",
            name="ck_hardware_stocktake_items_actual",
        ),
        Index("ix_hardware_stocktake_items_take", "stocktake_id"),
        Index("ix_hardware_stocktake_items_material", "material_id"),
        {"schema": "warehouse"},
    )

    stocktake_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_stocktakes.id"),
        nullable=False,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_materials.id"),
        nullable=False,
    )
    code: Mapped[str | None] = mapped_column(String(50), comment="物料编码快照")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="品名快照")
    spec: Mapped[str | None] = mapped_column(String(200), comment="规格快照")
    unit: Mapped[str | None] = mapped_column(String(20), comment="单位快照")
    unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), comment="单价快照（差异金额=unit_price×差异）"
    )
    book_qty: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, comment="账存（生成时 Σ accepted 批次余额）"
    )
    actual_qty: Mapped[Decimal | None] = mapped_column(
        _QTY, comment="实盘（NULL=未盘）"
    )
    diff_qty: Mapped[Decimal | None] = mapped_column(
        _QTY, comment="差异=实盘−账存（实盘后算）"
    )
    diff_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), comment="差异金额=unit_price×差异（单价 NULL 则 NULL）"
    )
    explanation: Mapped[str | None] = mapped_column(
        String(500), comment="差异说明（行级）"
    )


class HardwareReturn(BaseModel):
    """五金库退库单（设计 §2.6）：退库人 → 部门负责人签 → 仓管员验收（不合格拒退）。

    明细=行式 JSON items（[{material 快照, qty, preferred_lot_id}]）——退库单
    行数少（单部门少量物料），不建子表。accepted 时批次回加（优先回原 lot 增
    remaining；原 lot 不存在则新建 return 来源批次）+ return_in 流水。
    """

    __tablename__ = "hardware_returns"
    __table_args__ = (
        Index(
            "uq_hardware_returns_no",
            "return_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "status IN ('draft', 'accepted', 'rejected')",
            name="ck_hardware_returns_status",
        ),
        Index("ix_hardware_returns_status", "status"),
        {"schema": "warehouse"},
    )

    return_no: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="退库单号 WJK-TK-YYMMDD-序号"
    )
    dept_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="退库部门")
    returned_by: Mapped[str] = mapped_column(String(100), nullable=False, comment="退库人")
    returned_by_open_id: Mapped[str | None] = mapped_column(
        String(100), comment="退库人飞书 open_id"
    )
    items: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="明细行：[{material_id, code, name, spec, unit, quantity,"
                " preferred_lot_id}]（仅 stocked）",
    )
    leader_signed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="部门负责人已签",
    )
    leader_signed_by: Mapped[str | None] = mapped_column(String(100), comment="签收负责人")
    leader_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
        comment="draft 待验收 / accepted 已回加 / rejected 拒退",
    )
    accepted_by: Mapped[str | None] = mapped_column(String(100), comment="验收仓管员")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(
        String(500), comment="不合格拒退原因（留证）"
    )
    lot_adjustments: Mapped[list[Any] | None] = mapped_column(
        JSONB, comment="批次回加结果 [{material, lot_no, mode: preferred/new, qty}]"
    )
    remark: Mapped[str | None] = mapped_column(Text)


class HardwarePurchasePlan(BaseModel):
    """五金库月度采购计划（设计 §2.6）：25 日快照 → P7 公式草案 → 人工编辑 → 导出。

    plan_month 'YYYY-MM' 唯一=同月重跑幂等键（未编辑行刷新、is_edited 行保留）。
    P7：月采购量 = 安全库存量 + 月使用量 − 25 日实际库存量（负取 0+备注）。
    """

    __tablename__ = "hardware_purchase_plans"
    __table_args__ = (
        Index(
            "uq_hardware_purchase_plans_month",
            "plan_month",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "status IN ('draft', 'exported')",
            name="ck_hardware_purchase_plans_status",
        ),
        {"schema": "warehouse"},
    )

    plan_month: Mapped[str] = mapped_column(
        String(7), nullable=False, comment="计划月 'YYYY-MM'（同月重跑幂等键）"
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft", server_default="draft",
        comment="draft 草案可编辑 / exported 已导出报采购",
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="25 日快照时间"
    )
    usage_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30",
        comment="月使用量回溯窗口（天）",
    )
    annotated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="AI 用量注释是否已跑（失败/关闭=False）",
    )
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exported_by: Mapped[str | None] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(Text)


class HardwarePurchasePlanItem(BaseModel):
    """计划明细行：物料快照 + P7 公式各列（与制度附件 4 表样列对齐）。"""

    __tablename__ = "hardware_purchase_plan_items"
    __table_args__ = (
        CheckConstraint("purchase_qty >= 0", name="ck_hardware_plan_items_purchase"),
        Index("ix_hardware_plan_items_plan", "purchase_plan_id"),
        Index("ix_hardware_plan_items_material", "material_id"),
        {"schema": "warehouse"},
    )

    purchase_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_purchase_plans.id"),
        nullable=False,
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.hardware_materials.id"),
        nullable=False,
    )
    code: Mapped[str | None] = mapped_column(String(50), comment="物料编码快照")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="品名快照")
    spec: Mapped[str | None] = mapped_column(String(200), comment="规格快照")
    unit: Mapped[str | None] = mapped_column(String(20), comment="单位快照")
    monthly_demand_total: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="月需求合计（5 部门 monthly_demands 求和）",
    )
    safety_stock: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="安全库存量快照",
    )
    stock_on_25th: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="当月 25 日实际库存量（on_hand 快照）",
    )
    monthly_usage: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="月使用量=近 30 天出库流水聚合（req_issue+urgent_issue）",
    )
    purchase_qty: Mapped[Decimal] = mapped_column(
        _QTY, nullable=False, default=Decimal("0"), server_default="0",
        comment="月度采购量=P7 公式（负取 0）；人工编辑后 is_edited",
    )
    ai_note: Mapped[str | None] = mapped_column(
        String(500),
        comment="AI 用量注释（近 3 月趋势/异常波动；建议态，人审核采纳不改数量）",
    )
    is_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="人工编辑标记（同月重跑保留此行人工值）",
    )
    remark: Mapped[str | None] = mapped_column(String(500))


class HardwareEnvLog(BaseModel):
    """五金库温湿度日检（设计 §2.6）：每日一行（log_date 唯一）。"""

    __tablename__ = "hardware_env_logs"
    __table_args__ = (
        Index(
            "uq_hardware_env_logs_date",
            "log_date",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    log_date: Mapped[date] = mapped_column(Date, nullable=False, comment="日期（每日一行）")
    temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 1), comment="温度 ℃"
    )
    humidity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 1), comment="湿度 %RH"
    )
    checked_by: Mapped[str | None] = mapped_column(String(100), comment="检查人")
    abnormal_note: Mapped[str | None] = mapped_column(
        String(500), comment="异常说明"
    )
