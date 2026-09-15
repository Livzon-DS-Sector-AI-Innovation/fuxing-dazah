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
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，{base_token 脱敏, table_id, enabled, note}）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


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
