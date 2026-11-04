"""五金库 ORM 模型（一期 7 张核心表，设计文档 §二）。

schema=warehouse、表名前缀 hardware_。数量精度统一 Numeric(18,3)；
时区 Asia/Shanghai（DateTime(timezone=True)）；movement.quantity 恒正、
direction 表方向。库存变动收口：只随入库单 accepted 与出库单 issued。

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
RECEIPT_SOURCES = ("ocr", "manual", "erp_import")  # ERP 变故后主通道=ocr（口径13）
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
