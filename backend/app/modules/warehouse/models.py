"""Warehouse ORM models: materials, locations, stocks, movements, stocktakes."""

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
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

MATERIAL_CATEGORIES = ("raw", "auxiliary", "packaging", "intermediate", "finished")
LOCATION_TYPES = ("normal", "cold", "danger")
MOVEMENT_DIRECTIONS = ("inbound", "outbound", "adjust")
MOVEMENT_SOURCE_TYPES = ("purchase", "production", "sale", "return", "stocktake", "other")


class WarehouseMaterial(BaseModel):
    """物料主数据：原辅料、包材、中间体、成品。"""

    __tablename__ = "warehouse_materials"
    __table_args__ = (
        Index(
            "uq_warehouse_materials_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "category IN ('raw', 'auxiliary', 'packaging', 'intermediate', 'finished')",
            name="ck_warehouse_materials_category",
        ),
        {"schema": "warehouse"},
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称")
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="分类: raw原料/auxiliary辅料/packaging包材/intermediate中间体/finished成品"
    )
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="规格型号")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="计量单位")
    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="安全库存，低于该值提醒",
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class WarehouseLocation(BaseModel):
    """库位：库存的存放位置。"""

    __tablename__ = "warehouse_locations"
    __table_args__ = (
        Index(
            "uq_warehouse_locations_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "location_type IN ('normal', 'cold', 'danger')",
            name="ck_warehouse_locations_type",
        ),
        {"schema": "warehouse"},
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="库位编码")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="库位名称")
    zone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="库区")
    aisle: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="巷道/排")
    shelf_row: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="货架行")
    shelf_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="货架层")
    location_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default="normal",
        comment="类型: normal常温/cold冷藏/danger危险品",
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class WarehouseStock(BaseModel):
    """现有库存：物料 + 批次 + 库位 唯一，由出入库与盘点维护。"""

    __tablename__ = "warehouse_stocks"
    __table_args__ = (
        Index(
            "uq_warehouse_stocks_key",
            "material_id",
            "batch_no",
            "location_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_stocks_material", "material_id"),
        Index("ix_warehouse_stocks_location", "location_id"),
        {"schema": "warehouse"},
    )

    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号，空串表示无批次"
    )
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    location_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="库位编码（冗余）")
    location_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="库位名称（冗余）")
    expiry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="批次效期（入库登记时录入，随入库更新）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal",
        comment="状态: normal/quarantine/frozen",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0", comment="库存数量"
    )


class WarehouseStockStatusLog(BaseModel):
    """库存状态流转日志：每次变更写入，append-only。"""

    __tablename__ = "stock_status_logs"
    __table_args__ = (
        Index("ix_warehouse_stock_status_logs_stock", "stock_id"),
        {"schema": "warehouse"},
    )

    stock_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.warehouse_stocks.id"),
        nullable=False,
        comment="关联库存行",
    )
    old_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="变更前状态")
    new_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="变更后状态")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更原因")
    operator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, comment="操作人")


class WarehouseMovement(BaseModel):
    """出入库记录：一行代表一次物料移动，创建/删除时同步更新库存。"""

    __tablename__ = "warehouse_movements"
    __table_args__ = (
        Index(
            "uq_warehouse_movements_no",
            "movement_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_movements_material", "material_id"),
        Index("ix_warehouse_movements_occurred", "occurred_at"),
        CheckConstraint(
            "direction IN ('inbound', 'outbound', 'adjust')",
            name="ck_warehouse_movements_direction",
        ),
        CheckConstraint(
            "source_type IN ('purchase', 'production', 'sale', 'return', 'stocktake', 'other')",
            name="ck_warehouse_movements_source_type",
        ),
        CheckConstraint("quantity > 0", name="ck_warehouse_movements_quantity_positive"),
        {"schema": "warehouse"},
    )

    movement_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="单据编号")
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="方向: inbound入库/outbound出库/adjust盘点调整"
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="来源: purchase采购/production生产/sale销售/return退料/stocktake盘点/other其他",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号，空串表示无批次"
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="数量，恒为正")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, comment="计量单位（冗余）")
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    location_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="库位编码（冗余）")
    location_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="库位名称（冗余）")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), comment="业务发生时间"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class WarehouseStocktake(BaseModel):
    """盘点单：draft 可改可删，confirm 后按实盘结果调整库存并生成调整流水。"""

    __tablename__ = "warehouse_stocktakes"
    __table_args__ = (
        Index(
            "uq_warehouse_stocktakes_no",
            "stocktake_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_warehouse_stocktakes_status",
        ),
        {"schema": "warehouse"},
    )

    stocktake_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="盘点单号")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", comment="状态: draft草稿/confirmed已确认"
    )
    scope_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="盘点范围库位，空表示全库"
    )
    scope_location_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="盘点范围库位编码（冗余）")
    scope_location_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="盘点范围库位名称（冗余）")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="确认时间")


class WarehouseStocktakeItem(BaseModel):
    """盘点明细：book_quantity 为盘点单创建时的账面快照。"""

    __tablename__ = "warehouse_stocktake_items"
    __table_args__ = (
        Index("ix_warehouse_stocktake_items_stocktake", "stocktake_id"),
        Index(
            "uq_warehouse_stocktake_items_key",
            "stocktake_id",
            "material_id",
            "batch_no",
            "location_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    stocktake_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号，空串表示无批次"
    )
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    location_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="库位编码（冗余）")
    location_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="库位名称（冗余）")
    book_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, comment="账面数量快照")
    counted_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="实盘数量，空表示未盘"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class WarehouseStockDailySnapshot(BaseModel):
    """库存日快照：按物料聚合的每日库存总量（驾驶舱环比/趋势的数据底座）。

    口径：仅 is_deleted=false 的库存行，按物料求和（跨批次/库位）。
    同日重跑幂等覆盖（唯一键 snapshot_date + material_id，部分索引）。
    """

    __tablename__ = "stock_daily_snapshots"
    __table_args__ = (
        Index(
            "uq_warehouse_stock_daily_snapshots_key",
            "snapshot_date",
            "material_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_stock_daily_snapshots_date", "snapshot_date"),
        {"schema": "warehouse"},
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照业务日")
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    total_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0",
        comment="当日库存总量（跨批次/库位求和）",
    )
    stock_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="当日库存行数（批次×库位）",
    )


class WarehouseAgentDraft(BaseModel):
    """Agent 识别草稿：识别→对齐→人工确认→写 Base 的两段式载体。"""

    __tablename__ = "warehouse_agent_drafts"
    __table_args__ = (
        Index(
            "uq_warehouse_agent_drafts_no",
            "draft_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_agent_drafts_status", "status"),
        {"schema": "warehouse"},
    )

    draft_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="草稿编号")
    scene: Mapped[str] = mapped_column(String(50), nullable=False, comment="场景: receipt/gmp_outbound/finished_outbound")
    source_image: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="来源图片 file token")
    recognized: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="模型原始识别结果"
    )
    aligned: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="主数据对齐后字段+置信度"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="created", server_default="created",
        comment="created/aligned/pending_confirm/confirmed/submitted/expired/cancelled",
    )
    target_base: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="目标 Base token")
    target_table: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="目标表 table_id")
    target_record_id: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="写入成功后回填的 record_id")
    created_by_open_id: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="发起人飞书 open_id")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="feishu", server_default="feishu",
        comment="来源渠道: feishu/web",
    )
    chat_id: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="发起会话 chat_id（回执按原渠道回复）")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="草稿过期时间")


class WarehouseAgentSession(BaseModel):
    """Agent 会话上下文：对话历史裁剪与草稿摘要注入的依据。"""

    __tablename__ = "warehouse_agent_sessions"
    __table_args__ = (
        Index(
            "uq_warehouse_agent_sessions_key",
            "chat_id",
            "user_open_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    chat_id: Mapped[str] = mapped_column(String(60), nullable=False, comment="飞书 chat_id（私聊为 p2p 标识）")
    user_open_id: Mapped[str] = mapped_column(String(60), nullable=False, comment="用户飞书 open_id")
    history: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="最近消息与轮次摘要"
    )


class WarehouseAgentAudit(BaseModel):
    """Agent 工具调用审计：每次工具调用的参数摘要/结果状态/耗时。"""

    __tablename__ = "warehouse_agent_audit"
    __table_args__ = (
        Index("ix_warehouse_agent_audit_tool", "tool_name"),
        Index("ix_warehouse_agent_audit_draft", "draft_id"),
        {"schema": "warehouse"},
    )

    tool_name: Mapped[str] = mapped_column(String(60), nullable=False, comment="工具名")
    args_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="参数摘要（截断）"
    )
    result_status: Mapped[str] = mapped_column(String(30), nullable=False, comment="ok/error/denied")
    error_code: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="错误码分类（如 1254062）")
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="耗时毫秒"
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="关联会话"
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="关联草稿"
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="关联计划"
    )


class WarehouseAgentPlan(BaseModel):
    """Agent 任务计划：多步任务分解与中断恢复的持久化载体。"""

    __tablename__ = "warehouse_agent_plans"
    __table_args__ = (
        Index(
            "uq_warehouse_agent_plans_no",
            "plan_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    plan_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="计划编号")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="任务标题")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]", comment="[{no,desc,status,note}]"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active",
        comment="active/done/abandoned",
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="所属会话"
    )
    created_by_open_id: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="发起人飞书 open_id")


class WarehouseAgentMemory(BaseModel):
    """Agent 长期记忆：用户偏好/业务惯例/术语别名，跨会话。"""

    __tablename__ = "warehouse_agent_memories"
    __table_args__ = (
        Index("ix_warehouse_agent_memories_scope", "scope", "owner_open_id"),
        {"schema": "warehouse"},
    )

    scope: Mapped[str] = mapped_column(String(20), nullable=False, comment="user/global")
    owner_open_id: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="用户 open_id（global 时为空）")
    memory_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="preference/convention/alias")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="记忆内容")
    hit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="注入命中计数（淘汰用）"
    )


class WarehouseMovementPlan(BaseModel):
    """出入库计划单：到货/领料的预计单据。

    状态机 planned → in_progress → completed（完成在生成出入库登记时回填
    movement_id）；非完成态可取消（必填原因）。计划单本身不直接变更库存。
    """

    __tablename__ = "movement_plans"
    __table_args__ = (
        Index(
            "uq_warehouse_movement_plans_no",
            "plan_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_warehouse_movement_plans_direction",
        ),
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'cancelled')",
            name="ck_warehouse_movement_plans_status",
        ),
        {"schema": "warehouse"},
    )

    plan_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="计划单号")
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="方向: inbound入库/outbound出库"
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="业务来源")
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号，空表示无批次"
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="计划数量，恒为正"
    )
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    location_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="库位编码（冗余）")
    location_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="库位名称（冗余）")
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="预计日期")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned", server_default="planned",
        comment="planned/in_progress/completed/cancelled",
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="取消原因")
    movement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="生成登记后回填的出入库记录ID"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class WarehouseAlertRule(BaseModel):
    """智能中心预警规则：阈值可调，扫描引擎读取。"""

    __tablename__ = "alert_rules"
    __table_args__ = (
        Index(
            "uq_warehouse_alert_rules_key",
            "rule_key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    rule_key: Mapped[str] = mapped_column(String(32), nullable=False, comment="规则键")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="规则名称")
    threshold: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="阈值（按规则键约定字段）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="是否启用"
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class WarehouseAlertRuleAudit(BaseModel):
    """预警规则变更审计（append-only）。"""

    __tablename__ = "alert_rule_audits"
    __table_args__ = (
        Index(
            "ix_warehouse_alert_rule_audits_key_created",
            "rule_key",
            "created_at",
        ),
        {"schema": "warehouse"},
    )

    rule_key: Mapped[str] = mapped_column(String(32), nullable=False, comment="规则键")
    action: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更前")
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更后")
    operator_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="操作人")


class WarehouseAlertRecord(BaseModel):
    """异常记录：扫描引擎产出，open/resolved 状态管理。"""

    __tablename__ = "alert_records"
    __table_args__ = (
        Index(
            "ix_warehouse_alert_records_key_material",
            "rule_key",
            "material_id",
        ),
        Index("ix_warehouse_alert_records_status", "status"),
        {"schema": "warehouse"},
    )

    rule_key: Mapped[str] = mapped_column(String(32), nullable=False, comment="规则键")
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="warning", server_default="warning",
        comment="级别: warning/critical",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
        comment="状态: open/resolved",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号（临期类用）"
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    location_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="库位编码（冗余）")
    location_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="库位名称（冗余）")
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="异常详情（数量/天数等）"
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WarehouseReplenishmentSuggestion(BaseModel):
    """补货建议：按物料唯一，随扫描刷新（handled/ignored 不覆盖）。"""

    __tablename__ = "replenishment_suggestions"
    __table_args__ = (
        Index(
            "uq_warehouse_replenishment_suggestions_material",
            "material_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_replenishment_suggestions_status", "status"),
        {"schema": "warehouse"},
    )

    material_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码（冗余）")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称（冗余）")
    avg_daily_outbound: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0",
        comment="日均出库消耗（近30天）",
    )
    days_cover: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="可支撑天数（当前库存/日均），零消耗为空"
    )
    suggested_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0",
        comment="建议采购量",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
        comment="pending/handled/ignored",
    )
    handled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WarehouseDailyBriefing(BaseModel):
    """每日晨报：聚合异常/建议/昨日出入库（brief_date 唯一，重生成覆盖）。"""

    __tablename__ = "daily_briefings"
    __table_args__ = (
        Index(
            "uq_warehouse_daily_briefings_date",
            "brief_date",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "warehouse"},
    )

    brief_date: Mapped[date] = mapped_column(Date, nullable=False, comment="晨报业务日")
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="晨报内容 JSON"
    )


class WarehouseSyncCheckRun(BaseModel):
    """对账运行：一次库存台账比对的批次记录。"""

    __tablename__ = "sync_check_runs"
    __table_args__ = (
        Index("ix_warehouse_sync_check_runs_status", "status"),
        {"schema": "warehouse"},
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running",
        comment="running/completed/failed",
    )
    total_local: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="本地总行数"
    )
    total_feishu: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="飞书总行数"
    )
    cnt_match: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="一致数"
    )
    cnt_missing_in_feishu: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="飞书缺失数"
    )
    cnt_mismatch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="数量不一致数"
    )
    cnt_missing_local: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="本地缺失数"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="耗时毫秒"
    )


class WarehouseSyncCheckResult(BaseModel):
    """对账差异明细（仅落非 match 行）。"""

    __tablename__ = "sync_check_results"
    __table_args__ = (
        Index("ix_warehouse_sync_check_results_run", "run_id"),
        Index("ix_warehouse_sync_check_results_status", "status"),
        {"schema": "warehouse"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("warehouse.sync_check_runs.id"),
        nullable=False,
        comment="关联运行",
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False,
        comment="missing_in_feishu/mismatch/missing_local",
    )
    material_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="物料编码")
    material_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="物料名称")
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default="", comment="批次号"
    )
    local_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="本地数量")
    feishu_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="飞书数量")
    feishu_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="飞书记录 ID")
    repair_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="修复状态: repaired=已按Base修复 / manual=待人工处置（V3.0 分期A）",
    )
    repaired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="修复时间"
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}", comment="差异详情"
    )


# ==================== 系统配置中心（设计稿 warehouse-system-config-design.md） ====================
# 与 safety 模块同名表结构对齐（schema=warehouse）；回退链：DB 活行 → env → registry 默认。


class AiModelProfile(BaseModel):
    """AI 模型配置（一行一组配置）。DB 为唯一权威；缺行/停用时 store 回退 env/registry 默认值。"""

    __tablename__ = "ai_model_profiles"
    __table_args__ = (
        Index(
            "uq_warehouse_ai_model_profiles_profile",
            "profile",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_ai_model_profiles_profile", "profile"),
        {"schema": "warehouse"},
    )

    profile: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="profile key（registry 注册，如 agent/agent_backup）",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="模型配置（默认值来自 registry.default_config，api_key 恒为空串不回显）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false 时读路径整行回落 env/registry 默认）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiConfigAudit(BaseModel):
    """AI 模型配置变更审计（append-only；before/after 中 api_key 脱敏为 ****后4位）。"""

    __tablename__ = "ai_config_audits"
    __table_args__ = (
        Index("ix_warehouse_ai_config_audits_profile_created", "profile", "created_at"),
        Index("ix_warehouse_ai_config_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    profile: Mapped[str] = mapped_column(String(32), nullable=False, comment="profile key")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，api_key 已脱敏）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，api_key 已脱敏）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class AiScenarioConfig(BaseModel):
    """AI 场景配置（一行一场景）。缺行 = 默认开启；enabled=false = 熔断。"""

    __tablename__ = "ai_scenario_configs"
    __table_args__ = (
        Index(
            "uq_warehouse_ai_scenario_configs_scenario",
            "scenario",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_ai_scenario_configs_scenario", "scenario"),
        {"schema": "warehouse"},
    )

    scenario: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="场景 key（registry 注册，DB 只能改值不能新增场景）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false = 熔断，统一入口抛 ScenarioDisabledError）",
    )
    model_profile: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="绑定 profile 名（agent/agent_backup）；NULL = 按场景默认",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiScenarioConfigAudit(BaseModel):
    """AI 场景配置变更审计（append-only；相位无密钥不脱敏）。"""

    __tablename__ = "ai_scenario_config_audits"
    __table_args__ = (
        Index(
            "ix_warehouse_ai_scenario_config_audits_scenario_created",
            "scenario",
            "created_at",
        ),
        Index("ix_warehouse_ai_scenario_config_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    scenario: Mapped[str] = mapped_column(String(64), nullable=False, comment="对应场景")
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment="动作: update/enable/disable")
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，{enabled, model_profile, note}）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，{enabled, model_profile, note}）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class BitableConnection(BaseModel):
    """Bitable 表级连接坐标（一行一张 Base 表）。DB 缺行/字段空 = 回落 env/代码快照。"""

    __tablename__ = "bitable_connections"
    __table_args__ = (
        Index(
            "uq_warehouse_bitable_connections_table_key",
            "table_key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_bitable_connections_table_key", "table_key"),
        {"schema": "warehouse"},
    )

    table_key: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="表 key（bitable_schema.TABLES 注册，如 material_receipt）",
    )
    base_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="Base app_token 覆盖（空 = 回落 env/快照）",
    )
    table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="表 table_id 覆盖（空 = 回落代码快照）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false = 显式停用该表，不回退默认）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class BitableConfigAudit(BaseModel):
    """Bitable 连接变更审计（append-only）。"""

    __tablename__ = "bitable_config_audits"
    __table_args__ = (
        Index("ix_warehouse_bitable_config_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    table_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="表 key")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/update_env/env_mode"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，{base_token 脱敏, table_id, enabled, note, env}）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class BitableEnvConnection(BaseModel):
    """Bitable 表级连接坐标（环境维度，V3.0 分期D §3.3 生产版切换准备）。

    一行 = 某表在某环境（test/prod）的坐标覆盖。resolve 链：
    环境行（当前 bitable_env_mode）→ 既有 bitable_connections 行 →
    env/settings → 代码快照。test 模式且无环境行时行为与历史完全一致。
    """

    __tablename__ = "bitable_env_connections"
    __table_args__ = (
        Index(
            "uq_warehouse_bitable_env_connections_key",
            "table_key",
            "env",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_bitable_env_connections_table_key", "table_key"),
        {"schema": "warehouse"},
    )

    table_key: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="表 key（bitable_schema.TABLES 注册，如 material_receipt）",
    )
    env: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="环境: test 测试版 / prod 生产版",
    )
    base_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="Base app_token 覆盖（空 = 回落既有连接行/env/快照）",
    )
    table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="表 table_id 覆盖（空 = 回落既有连接行/代码快照）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false = 该环境显式停用该表，不回退默认）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class RuntimeConfig(BaseModel):
    """Agent 运行参数（一行一键）。DB 缺行 = 回落 env/registry 默认。"""

    __tablename__ = "runtime_configs"
    __table_args__ = (
        Index(
            "uq_warehouse_runtime_configs_key",
            "key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_runtime_configs_key", "key"),
        {"schema": "warehouse"},
    )

    key: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="参数 key（runtime_registry 注册，DB 只能改值不能新增）",
    )
    value: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=None, comment="参数值（按注册表类型写入）"
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class RuntimeConfigAudit(BaseModel):
    """运行参数变更审计（append-only）。"""

    __tablename__ = "runtime_config_audits"
    __table_args__ = (
        Index("ix_warehouse_runtime_config_audits_key_created", "key", "created_at"),
        Index("ix_warehouse_runtime_config_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False, comment="参数 key")
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment="动作: update/reset")
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更前")
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更后")
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class SchedulerTaskConfig(BaseModel):
    """定时任务/告警目标配置（一行一任务；只能改值不能新增 job）。"""

    __tablename__ = "scheduler_task_configs"
    __table_args__ = (
        Index(
            "uq_warehouse_scheduler_task_configs_job",
            "job_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_scheduler_task_configs_job", "job_name"),
        {"schema": "warehouse"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="任务 key（scheduler_registry 注册，如 system_alert）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="是否启用"
    )
    schedule: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        comment='调度（{"type":"interval","seconds":300} / {"type":"cron","expr":"..."}；null=事件触发）',
    )
    target_chat_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书投递目标（群 chat_id；空 = 回落 env 兜底）"
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class SchedulerConfigAudit(BaseModel):
    """任务配置变更审计（append-only）。"""

    __tablename__ = "scheduler_config_audits"
    __table_args__ = (
        Index("ix_warehouse_scheduler_config_audits_job_created", "job_name", "created_at"),
        Index("ix_warehouse_scheduler_config_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    job_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务 key")
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment="动作: update/enable/disable")
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更前")
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更后")
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class WarehousePushTask(BaseModel):
    """推送任务配置（一行一任务；只能改值不能新增，push_center registry 注册）。"""

    __tablename__ = "push_tasks"
    __table_args__ = (
        Index(
            "uq_warehouse_push_tasks_task",
            "task_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_push_tasks_task", "task_name"),
        {"schema": "warehouse"},
    )

    task_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="任务 key（push_center registry 注册，如 morning_report）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="是否启用"
    )
    schedule: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="调度 daily/weekly/monthly/yearly/interval（引擎五态）；event 任务为 null；空值=回落 registry 默认",
    )
    targets: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="推送目标（逗号分隔群 chat_id/个人 open_id；空 = 回落 env 兜底）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class WarehousePushTaskAudit(BaseModel):
    """推送任务配置变更审计（append-only）。"""

    __tablename__ = "push_task_audits"
    __table_args__ = (
        Index("ix_warehouse_push_task_audits_task_created", "task_name", "created_at"),
        Index("ix_warehouse_push_task_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    task_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务 key")
    action: Mapped[str] = mapped_column(String(32), nullable=False, comment="动作: update/enable/disable")
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更前")
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变更后")
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class WarehousePushLog(BaseModel):
    """推送日志（append-only；每次执行每目标一行，无目标跳过记一行）。"""

    __tablename__ = "push_logs"
    __table_args__ = (
        Index("ix_warehouse_push_logs_task_slot", "task_name", "slot"),
        Index("ix_warehouse_push_logs_task_created", "task_name", "created_at"),
        Index("ix_warehouse_push_logs_created", "created_at"),
        {"schema": "warehouse"},
    )

    task_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务 key")
    scene: Mapped[str] = mapped_column(String(64), nullable=False, comment="内容场景（生成器注册 key）")
    trigger: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="触发: scheduled/manual/event"
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="引擎执行时刻（interval 冷却判断基准）"
    )
    slot: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划槽位（日历型调度当日判重；interval/event 为空）"
    )
    target: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="目标 chat_id/open_id（无目标跳过行为空）"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="success/failed/skipped")
    message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 message_id（dry_run 为占位值）"
    )
    error: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="失败/跳过原因")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="发送耗时毫秒")


class WarehouseConfirmRequest(BaseModel):
    """通用业务确认单（V3.0 分期A 确认门；1C 二值：确认/取消，无会签）。

    确认动作 = 按映射回写 Base 字段（ref_table + ref_record_ids + writeback）；
    取消动作 = 仅记审计不改数。状态机与草稿确认链（agent/confirm.py）同构
    但独立成表——登记场景继续走 AgentDraft，业务确认走本表。
    """

    __tablename__ = "confirm_requests"
    __table_args__ = (
        Index(
            "uq_warehouse_confirm_requests_no",
            "request_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_confirm_requests_business_status", "business_type", "status"),
        Index("ix_warehouse_confirm_requests_status_created", "status", "created_at"),
        {"schema": "warehouse"},
    )

    request_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="确认单号 CR-yyyymmddHHMMSS-XXXXXX")
    business_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="业务类型（如 unqualified_disposition）"
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="卡片标题")
    summary: Mapped[str] = mapped_column(Text, nullable=False, comment="卡片正文（markdown，含清单摘要）")
    ref_table: Mapped[str] = mapped_column(String(64), nullable=False, comment="回写目标 Base 表 key")
    ref_record_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, comment="回写目标 record_id 列表"
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="业务快照（审计/回执渲染用）"
    )
    target: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="确认卡投递目标（群 chat_id / 个人 open_id）"
    )
    writeback: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="回写字段映射 {Base字段名: 值}（确认后逐条写入 ref 记录）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="pending/confirmed/cancelled/expired/failed"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="过期时间（默认 24h）")
    confirmed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="确认操作人 open_id（点击者；目标内任何人可确认）"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="确认时间")
    resend_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="重发次数"
    )
    card_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="确认卡 message_id（PATCH 原卡用；重发后为最新一张）"
    )


class WarehouseConfirmAudit(BaseModel):
    """确认单生命周期审计（append-only：create/confirm/cancel/expire/resend/writeback）。"""

    __tablename__ = "confirm_request_audits"
    __table_args__ = (
        Index("ix_warehouse_confirm_request_audits_no_created", "request_no", "created_at"),
        Index("ix_warehouse_confirm_request_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    request_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="确认单号")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: create/confirm/cancel/expire/resend/writeback_ok/writeback_failed"
    )
    operator_open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="操作人 open_id（系统动作为空）"
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="补充明细（回写条数/失败原因等）"
    )


class WarehouseQcStatus(BaseModel):
    """QC 状态镜像（V3.0 分期B 链路4）：material_receipt 单条记录的
    QC 取样/出报/QA 放行状态快照，扫描任务 upsert（record_id 幂等）。

    只读展示（库存列表 join / 驾驶舱待办）+ 变迁检测（新旧快照对比，
    放行通知只推一次）；Base 为权威（2B），本表不承载任何写路径。
    """

    __tablename__ = "qc_status"
    __table_args__ = (
        Index(
            "uq_warehouse_qc_status_record",
            "record_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_warehouse_qc_status_batch", "batch_no"),
        {"schema": "warehouse"},
    )

    record_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="material_receipt record_id（唯一，幂等键）"
    )
    batch_no: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="", comment="物料批号")
    material_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default="", comment="物料名称"
    )
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="入库日期（超期判断与展示）")
    sample_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="QC取样情况: 已取样/未取样/无需取"
    )
    report_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="QC出报: 已出报（合格）/已出报（不合格）/未出报/免检物料"
    )
    release_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="QA放行: 放行/否决/条件放行"
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="最近一次扫描时间"
    )
