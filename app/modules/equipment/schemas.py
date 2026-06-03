"""Equipment request and response schemas live here."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

EquipmentStatus = Literal["在用", "备用", "维修中", "停用", "报废"]


# ==================== 设备分类 ====================
class EquipmentCategoryCreate(BaseModel):
    """创建设备分类请求"""

    name: str = Field(..., min_length=1, max_length=100, description="分类名称")
    code: str = Field(..., min_length=1, max_length=50, description="分类代码")
    parent_id: uuid.UUID | None = Field(default=None, description="父分类ID")
    description: str | None = Field(default=None, description="分类描述")


class EquipmentCategoryUpdate(BaseModel):
    """更新设备分类请求"""

    name: str | None = Field(
        default=None, min_length=1, max_length=100, description="分类名称"
    )
    code: str | None = Field(
        default=None, min_length=1, max_length=50, description="分类代码"
    )
    parent_id: uuid.UUID | None = Field(default=None, description="父分类ID")
    description: str | None = Field(default=None, description="分类描述")


class EquipmentCategoryResponse(BaseModel):
    """设备分类响应"""

    id: uuid.UUID
    name: str
    code: str
    parent_id: uuid.UUID | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class EquipmentCategoryTree(EquipmentCategoryResponse):
    """设备分类树形结构"""

    children: list["EquipmentCategoryTree"] = []


# ==================== 位置管理 ====================
class LocationCreate(BaseModel):
    """创建位置请求"""

    name: str = Field(..., min_length=1, max_length=100, description="位置名称")
    code: str = Field(..., min_length=1, max_length=50, description="位置代码")
    parent_id: uuid.UUID | None = Field(default=None, description="父位置ID")
    description: str | None = Field(default=None, description="位置描述")


class LocationUpdate(BaseModel):
    """更新位置请求"""

    name: str | None = Field(
        default=None, min_length=1, max_length=100, description="位置名称"
    )
    code: str | None = Field(
        default=None, min_length=1, max_length=50, description="位置代码"
    )
    parent_id: uuid.UUID | None = Field(default=None, description="父位置ID")
    description: str | None = Field(default=None, description="位置描述")


class LocationResponse(BaseModel):
    """位置响应"""

    id: uuid.UUID
    name: str
    code: str
    parent_id: uuid.UUID | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class LocationTree(LocationResponse):
    """位置树形结构"""

    children: list["LocationTree"] = []


# ==================== 设备管理 ====================
class EquipmentCreate(BaseModel):
    """创建设备请求"""

    name: str = Field(..., min_length=1, max_length=200, description="设备名称")
    category_id: uuid.UUID = Field(..., description="设备分类ID")
    location_id: uuid.UUID = Field(..., description="设备位置ID")
    status: EquipmentStatus = Field(
        default="在用", description="设备状态：在用/备用/维修中/停用/报废"
    )
    model: str | None = Field(default=None, max_length=100, description="设备型号")
    specification: str | None = Field(
        default=None, max_length=200, description="设备规格"
    )
    manufacturer: str | None = Field(
        default=None, max_length=200, description="制造商"
    )
    supplier: str | None = Field(
        default=None, max_length=200, description="供应商"
    )
    production_date: date | None = Field(default=None, description="出厂日期")
    commissioning_date: date | None = Field(default=None, description="投用日期")
    description: str | None = Field(default=None, description="设备描述")


class EquipmentUpdate(BaseModel):
    """更新设备请求"""

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="设备名称"
    )
    category_id: uuid.UUID | None = Field(default=None, description="设备分类ID")
    location_id: uuid.UUID | None = Field(default=None, description="设备位置ID")
    status: EquipmentStatus | None = Field(
        default=None, description="设备状态：在用/备用/维修中/停用/报废"
    )
    model: str | None = Field(default=None, max_length=100, description="设备型号")
    specification: str | None = Field(
        default=None, max_length=200, description="设备规格"
    )
    manufacturer: str | None = Field(
        default=None, max_length=200, description="制造商"
    )
    supplier: str | None = Field(
        default=None, max_length=200, description="供应商"
    )
    production_date: date | None = Field(default=None, description="出厂日期")
    commissioning_date: date | None = Field(default=None, description="投用日期")
    description: str | None = Field(default=None, description="设备描述")


class EquipmentResponse(BaseModel):
    """设备响应"""

    id: uuid.UUID
    equipment_no: str
    name: str
    category_id: uuid.UUID
    location_id: uuid.UUID
    status: EquipmentStatus
    model: str | None
    specification: str | None
    manufacturer: str | None
    supplier: str | None
    production_date: date | None
    commissioning_date: date | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class EquipmentStatistics(BaseModel):
    """设备统计"""

    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_location: dict[str, int]
