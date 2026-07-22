"""Maintenance plan schemas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ==================== 维护计划 ====================
MaintenancePlanType = Literal["预防性维护", "预测性维护"]
FrequencyUnit = Literal["天", "周", "月", "年"]
MaintenancePlanStatus = Literal["启用", "停用", "已完成"]


class MaintenancePlanCreate(BaseModel):
    """创建维护计划请求"""

    equipment_id: uuid.UUID | None = Field(
        default=None, description="设备ID（与 category_id 二选一）"
    )
    category_id: uuid.UUID | None = Field(
        default=None, description="设备分类ID（与 equipment_id 二选一）"
    )
    plan_name: str = Field(..., max_length=200, description="计划名称")
    plan_type: MaintenancePlanType = Field(
        default="预防性维护", description="计划类型"
    )
    frequency: int = Field(..., ge=1, description="维护频率数值")
    frequency_unit: FrequencyUnit = Field(..., description="频率单位")
    last_maintenance_date: date | None = Field(
        default=None, description="上次维护日期"
    )
    executor_id: uuid.UUID | None = Field(
        default=None, description="执行人ID"
    )
    maintenance_content: str | None = Field(
        default=None, description="维护内容说明"
    )
    remark: str | None = Field(default=None, description="备注")

    @model_validator(mode="after")
    def check_equipment_or_category(self) -> "MaintenancePlanCreate":
        has_equipment = self.equipment_id is not None
        has_category = self.category_id is not None
        if not has_equipment and not has_category:
            raise ValueError("equipment_id 和 category_id 必须至少提供一个")
        if has_equipment and has_category:
            raise ValueError("equipment_id 和 category_id 不能同时提供，请二选一")
        return self


class MaintenancePlanUpdate(BaseModel):
    """更新维护计划请求"""

    plan_name: str | None = Field(
        default=None, max_length=200, description="计划名称"
    )
    plan_type: MaintenancePlanType | None = Field(
        default=None, description="计划类型"
    )
    frequency: int | None = Field(default=None, ge=1, description="维护频率数值")
    frequency_unit: FrequencyUnit | None = Field(
        default=None, description="频率单位"
    )
    last_maintenance_date: date | None = Field(
        default=None, description="上次维护日期"
    )
    executor_id: uuid.UUID | None = Field(
        default=None, description="执行人ID"
    )
    maintenance_content: str | None = Field(
        default=None, description="维护内容说明"
    )
    status: MaintenancePlanStatus | None = Field(default=None, description="状态")
    remark: str | None = Field(default=None, description="备注")


class MaintenancePlanResponse(BaseModel):
    """维护计划响应"""

    id: uuid.UUID
    equipment_id: uuid.UUID | None
    category_id: uuid.UUID | None
    plan_name: str
    plan_type: MaintenancePlanType
    frequency: int
    frequency_unit: FrequencyUnit
    last_maintenance_date: date | None
    next_maintenance_date: date | None
    executor_id: uuid.UUID | None
    executor_name: str | None = None
    maintenance_content: str | None
    status: MaintenancePlanStatus
    remark: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    equipment_name: str | None = None
    equipment_no: str | None = None
    category_name: str | None = None

    model_config = {"from_attributes": True}
