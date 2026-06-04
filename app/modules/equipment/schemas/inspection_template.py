"""Inspection template schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ==================== 巡检模板 ====================
class InspectionTemplateItemCreate(BaseModel):
    """创建巡检模板检查项请求"""

    item_name: str = Field(..., max_length=200, description="检查项名称")
    item_description: str | None = Field(default=None, description="检查项说明")
    expected_result: str | None = Field(
        default=None, max_length=200, description="预期结果/标准值"
    )
    check_method: str | None = Field(
        default=None, max_length=100, description="检查方法"
    )
    sort_order: int = Field(default=0, ge=0, description="排序序号")


class InspectionTemplateItemUpdate(BaseModel):
    """更新巡检模板检查项请求"""

    item_name: str | None = Field(
        default=None, max_length=200, description="检查项名称"
    )
    item_description: str | None = Field(default=None, description="检查项说明")
    expected_result: str | None = Field(
        default=None, max_length=200, description="预期结果/标准值"
    )
    check_method: str | None = Field(
        default=None, max_length=100, description="检查方法"
    )
    sort_order: int | None = Field(default=None, ge=0, description="排序序号")


class InspectionTemplateItemResponse(BaseModel):
    """巡检模板检查项响应"""

    id: uuid.UUID
    template_id: uuid.UUID
    item_name: str
    item_description: str | None
    expected_result: str | None
    check_method: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InspectionTemplateCreate(BaseModel):
    """创建巡检模板请求"""

    name: str = Field(..., max_length=200, description="模板名称")
    description: str | None = Field(default=None, description="模板描述")
    equipment_category_id: uuid.UUID | None = Field(
        default=None, description="适用设备分类ID"
    )
    items: list[InspectionTemplateItemCreate] = Field(
        default_factory=list, description="检查项列表"
    )


class InspectionTemplateUpdate(BaseModel):
    """更新巡检模板请求"""

    name: str | None = Field(default=None, max_length=200, description="模板名称")
    description: str | None = Field(default=None, description="模板描述")
    equipment_category_id: uuid.UUID | None = Field(
        default=None, description="适用设备分类ID"
    )
    is_active: bool | None = Field(default=None, description="是否启用")


class InspectionTemplateResponse(BaseModel):
    """巡检模板响应"""

    id: uuid.UUID
    name: str
    description: str | None
    equipment_category_id: uuid.UUID | None
    is_active: bool
    items: list[InspectionTemplateItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


# ==================== 巡检记录 ====================
class InspectionRecordItem(BaseModel):
    """巡检记录项"""
    template_item_id: uuid.UUID = Field(..., description="检查项ID")
    result: str = Field(..., description="结果：正常/异常/跳过")
    actual_value: str | None = Field(default=None, description="实际值")
    remark: str | None = Field(default=None, description="备注")


class InspectionCompleteRequest(BaseModel):
    """巡检完成请求（提交所有检查项结果）"""
    records: list[InspectionRecordItem] = Field(
        ..., min_length=1, description="检查项结果列表"
    )


class InspectionRecordResponse(BaseModel):
    """巡检记录响应"""
    id: uuid.UUID
    work_order_id: uuid.UUID
    template_item_id: uuid.UUID
    result: str
    actual_value: str | None
    remark: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
