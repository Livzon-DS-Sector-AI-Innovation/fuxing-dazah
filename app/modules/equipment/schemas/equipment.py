"""Equipment request and response schemas live here."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

EquipmentStatus = Literal["在用", "备用", "维修中", "停用", "报废"]
EquipmentImportance = Literal["高", "中", "低"]


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
    equipment_no: str = Field(
        ..., min_length=1, max_length=50, description="设备编号（手动输入，需唯一）"
    )
    category_ids: list[uuid.UUID] = Field(
        ..., min_length=1, description="设备分类ID列表（支持多分类）"
    )
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
    importance: EquipmentImportance = Field(default="低", description="设备重要性：高/中/低")
    warranty_expire_date: date | None = Field(default=None, description="保修到期日")
    asset_value: float | None = Field(default=None, ge=0, description="资产原值（元）")
    depreciation_years: int | None = Field(default=None, ge=1, description="折旧年限")
    technical_params: dict | None = Field(default=None, description="技术参数")
    department_id: uuid.UUID | None = Field(
        default=None, description="归属部门ID，逻辑引用 identity.departments.id"
    )
    responsible_person_id: uuid.UUID | None = Field(
        default=None, description="负责人ID，逻辑引用 identity.users.id；未设置时由部门负责人推导"
    )


class EquipmentUpdate(BaseModel):
    """更新设备请求"""

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="设备名称"
    )
    category_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, description="设备分类ID列表（支持多分类）"
    )
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
    importance: EquipmentImportance | None = Field(default=None, description="设备重要性：高/中/低")
    warranty_expire_date: date | None = Field(default=None, description="保修到期日")
    asset_value: float | None = Field(default=None, ge=0, description="资产原值（元）")
    depreciation_years: int | None = Field(default=None, ge=1, description="折旧年限")
    technical_params: dict | None = Field(default=None, description="技术参数")
    department_id: uuid.UUID | None = Field(
        default=None, description="归属部门ID，逻辑引用 identity.departments.id"
    )
    responsible_person_id: uuid.UUID | None = Field(
        default=None, description="负责人ID，逻辑引用 identity.users.id；未设置时由部门负责人推导"
    )


class EquipmentResponse(BaseModel):
    """设备响应"""

    id: uuid.UUID
    equipment_no: str
    name: str
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    category_names: str | None = None
    location_id: uuid.UUID
    location_name: str | None = None
    status: EquipmentStatus
    model: str | None
    specification: str | None
    manufacturer: str | None
    supplier: str | None
    production_date: date | None
    commissioning_date: date | None
    description: str | None
    importance: str
    warranty_expire_date: date | None
    asset_value: float | None
    depreciation_years: int | None
    technical_params: dict | None
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    responsible_person_id: uuid.UUID | None = None
    responsible_person_name: str | None = None
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


# ==================== Excel 导入 ====================
class ImportRowError(BaseModel):
    """单行导入错误"""

    row: int = Field(..., description="Excel 行号（从 2 开始，第 1 行为表头）")
    message: str = Field(..., description="错误描述")


class EquipmentImportResponse(BaseModel):
    """Excel 导入结果"""

    imported: int = Field(..., description="成功导入数量")
    skipped: int = Field(..., description="跳过数量")
    errors: list[ImportRowError] = Field(default_factory=list, description="错误明细")
    warnings: list[ImportRowError] = Field(default_factory=list, description="警告明细")
