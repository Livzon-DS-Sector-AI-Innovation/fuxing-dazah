"""Warehouse ORM models: materials, locations, stocks, movements, stocktakes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Integer,
    DateTime,
    Index,
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
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0", comment="库存数量"
    )


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
