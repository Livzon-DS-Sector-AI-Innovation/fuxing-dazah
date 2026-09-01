"""Warehouse ORM models: materials, locations, stocks, movements, stocktakes."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
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
