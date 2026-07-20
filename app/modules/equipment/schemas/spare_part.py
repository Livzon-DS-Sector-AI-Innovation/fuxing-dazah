"""Spare part schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ==================== 备件主数据 ====================
class SparePartCreate(BaseModel):
    """创建备件请求"""

    code: str = Field(
        ..., min_length=1, max_length=50, description="备件编码"
    )
    name: str = Field(
        ..., min_length=1, max_length=200, description="备件名称"
    )
    specification: str | None = Field(
        default=None, max_length=200, description="规格型号"
    )
    unit: str = Field(
        ..., min_length=1, max_length=20, description="计量单位"
    )
    category: str | None = Field(
        default=None, max_length=50, description="备件分类"
    )
    default_supplier: str | None = Field(
        default=None, max_length=200, description="默认供应商"
    )
    unit_price: float | None = Field(
        default=None, ge=0, description="参考单价"
    )
    is_active: bool = Field(default=True, description="是否启用")
    department_id: uuid.UUID | None = Field(
        default=None, description="归属部门ID"
    )


class SparePartUpdate(BaseModel):
    """更新备件请求"""

    code: str | None = Field(
        default=None, min_length=1, max_length=50, description="备件编码"
    )
    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="备件名称"
    )
    specification: str | None = Field(
        default=None, max_length=200, description="规格型号"
    )
    unit: str | None = Field(
        default=None, min_length=1, max_length=20, description="计量单位"
    )
    category: str | None = Field(
        default=None, max_length=50, description="备件分类"
    )
    default_supplier: str | None = Field(
        default=None, max_length=200, description="默认供应商"
    )
    unit_price: float | None = Field(
        default=None, ge=0, description="参考单价"
    )
    is_active: bool | None = Field(
        default=None, description="是否启用"
    )
    department_id: uuid.UUID | None = Field(
        default=None, description="归属部门ID"
    )


class SparePartResponse(BaseModel):
    """备件响应"""
    id: uuid.UUID
    code: str
    name: str
    specification: str | None
    unit: str
    category: str | None
    default_supplier: str | None
    unit_price: float | None
    is_active: bool
    equipment_count: int = 0
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


# ==================== 库存 ====================
class StockResponse(BaseModel):
    """库存响应"""
    id: uuid.UUID
    spare_part_id: uuid.UUID
    warehouse_location: str | None
    current_qty: int
    safety_qty: int
    min_order_qty: int

    model_config = {"from_attributes": True}


class StockInboundRequest(BaseModel):
    """入库请求"""
    quantity: int = Field(..., ge=1, description="入库数量")
    warehouse_location: str | None = Field(default=None, description="库位")
    remark: str | None = Field(default=None, description="备注")


class StockAdjustRequest(BaseModel):
    """盘点调整请求"""
    new_qty: int = Field(..., ge=0, description="调整后数量")
    remark: str | None = Field(default=None, description="备注")


class StockWarningResponse(BaseModel):
    """库存预警响应"""
    spare_part: SparePartResponse
    stock: StockResponse
    shortage: int

    model_config = {"from_attributes": True}


# ==================== 设备-备件关联 ====================
class EquipmentSparePartCreate(BaseModel):
    """设备-备件关联请求"""
    equipment_id: uuid.UUID = Field(..., description="设备ID")
    quantity: int = Field(default=1, ge=1, description="需要数量")


class EquipmentSparePartResponse(BaseModel):
    """设备-备件关联响应"""
    id: uuid.UUID
    equipment_id: uuid.UUID
    spare_part_id: uuid.UUID
    quantity: int

    model_config = {"from_attributes": True}


class EquipmentSparePartExtended(EquipmentSparePartResponse):
    """设备-备件关联响应（含设备摘要）"""
    equipment_no: str | None = None
    equipment_name: str | None = None


class OutboundTransactionResponse(BaseModel):
    """消耗流水响应"""
    id: uuid.UUID
    spare_part_id: uuid.UUID
    spare_part_code: str | None = None
    spare_part_name: str | None = None
    specification: str | None = None
    unit: str | None = None
    quantity: int
    work_order_id: uuid.UUID | None = None
    work_order_no: str | None = None
    equipment_name: str | None = None
    consumed_at: datetime
    remark: str | None = None

    model_config = {"from_attributes": True}


# ==================== 设备备件消耗历史 ====================
class EquipmentConsumptionRecord(BaseModel):
    """设备备件消耗记录"""
    id: uuid.UUID
    spare_part_id: uuid.UUID
    spare_part_code: str | None = None
    spare_part_name: str | None = None
    specification: str | None = None
    unit: str | None = None
    quantity: int
    work_order_id: uuid.UUID | None = None
    work_order_no: str | None = None
    consumed_at: datetime
    remark: str | None = None

    model_config = {"from_attributes": True}
