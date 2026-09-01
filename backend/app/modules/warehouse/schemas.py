"""Warehouse request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, computed_field

StrUUID = Annotated[str, BeforeValidator(str)]

MaterialCategory = Literal["raw", "auxiliary", "packaging", "intermediate", "finished"]
LocationType = Literal["normal", "cold", "danger"]
MovementDirection = Literal["inbound", "outbound"]
MovementSourceType = Literal["purchase", "production", "sale", "return", "other"]


# ── 物料主数据 ──


class MaterialCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="物料编码")
    name: str = Field(..., min_length=1, max_length=200, description="物料名称")
    category: MaterialCategory = Field(..., description="分类")
    spec: str | None = Field(default=None, max_length=200, description="规格型号")
    unit: str = Field(..., min_length=1, max_length=20, description="计量单位")
    safety_stock: float = Field(default=0, ge=0, description="安全库存")
    remark: str | None = Field(default=None, description="备注")


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: MaterialCategory | None = None
    spec: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    safety_stock: float | None = Field(default=None, ge=0)
    remark: str | None = None


class MaterialResponse(BaseModel):
    id: StrUUID
    code: str
    name: str
    category: str
    spec: str | None
    unit: str
    safety_stock: float
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 库位 ──


class LocationCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="库位编码")
    name: str = Field(..., min_length=1, max_length=200, description="库位名称")
    location_type: LocationType = Field(default="normal", description="库位类型")
    remark: str | None = Field(default=None, description="备注")


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_type: LocationType | None = None
    remark: str | None = None


class LocationResponse(BaseModel):
    id: StrUUID
    code: str
    name: str
    location_type: str
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 库存 ──


class StockResponse(BaseModel):
    id: StrUUID
    material_id: StrUUID
    material_code: str
    material_name: str
    category: str | None = None
    unit: str | None = None
    safety_stock: float | None = None
    batch_no: str
    location_id: StrUUID
    location_code: str
    location_name: str
    quantity: float

    model_config = {"from_attributes": True}


# ── 出入库 ──


class MovementCreate(BaseModel):
    direction: MovementDirection = Field(..., description="inbound入库/outbound出库")
    source_type: MovementSourceType = Field(..., description="业务来源")
    material_id: StrUUID = Field(..., description="物料ID")
    batch_no: str = Field(default="", max_length=100, description="批次号，空表示无批次")
    quantity: float = Field(..., gt=0, description="数量")
    location_id: StrUUID = Field(..., description="库位ID")
    occurred_at: datetime | None = Field(default=None, description="业务发生时间，空则取当前时间")
    remark: str | None = Field(default=None, description="备注")


class MovementResponse(BaseModel):
    id: StrUUID
    movement_no: str
    direction: str
    source_type: str
    material_id: StrUUID
    material_code: str
    material_name: str
    batch_no: str
    quantity: float
    unit: str
    location_id: StrUUID
    location_code: str
    location_name: str
    occurred_at: datetime
    remark: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 盘点 ──


class StocktakeCreate(BaseModel):
    scope_location_id: StrUUID | None = Field(default=None, description="盘点范围库位，空表示全库")
    remark: str | None = Field(default=None, description="备注")


class StocktakeItemUpdateIn(BaseModel):
    item_id: StrUUID
    counted_quantity: float | None = Field(default=None, ge=0, description="实盘数量，空表示未盘")
    remark: str | None = None


class StocktakeUpdate(BaseModel):
    items: list[StocktakeItemUpdateIn] = Field(..., min_length=1, description="盘点明细更新列表")


class StocktakeItemResponse(BaseModel):
    id: StrUUID
    material_id: StrUUID
    material_code: str
    material_name: str
    batch_no: str
    location_id: StrUUID
    location_code: str
    location_name: str
    book_quantity: float
    counted_quantity: float | None
    remark: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def difference(self) -> float | None:
        """盘差 = 实盘 - 账面。"""
        if self.counted_quantity is None:
            return None
        return round(self.counted_quantity - self.book_quantity, 4)

    model_config = {"from_attributes": True}


class StocktakeResponse(BaseModel):
    id: StrUUID
    stocktake_no: str
    status: str
    scope_location_id: StrUUID | None
    scope_location_code: str | None
    scope_location_name: str | None
    remark: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[StocktakeItemResponse] = []

    model_config = {"from_attributes": True}


# ── 概览 ──


class OverviewResponse(BaseModel):
    material_count: int
    location_count: int
    stock_sku_count: int
    low_stock_materials: list[str]
    today_inbound_quantity: float
    today_outbound_quantity: float
