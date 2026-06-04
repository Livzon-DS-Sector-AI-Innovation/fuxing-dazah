"""Maintenance plan schemas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ==================== 维护计划 ====================
MaintenancePlanType = Literal["预防性维护", "预测性维护"]
FrequencyUnit = Literal["天", "周", "月", "年"]
MaintenancePlanStatus = Literal["启用", "停用", "已完成"]


class MaintenancePlanCreate(BaseModel):
    """创建维护计划请求"""

    equipment_id: uuid.UUID = Field(..., description="设备ID")
    plan_name: str = Field(..., max_length=200, description="计划名称")
    plan_type: MaintenancePlanType = Field(
        default="预防性维护", description="计划类型"
    )
    frequency: int = Field(..., ge=1, description="维护频率数值")
    frequency_unit: FrequencyUnit = Field(..., description="频率单位")
    last_maintenance_date: date | None = Field(
        default=None, description="上次维护日期"
    )
    responsible_person_id: uuid.UUID | None = Field(
        default=None, description="负责人ID"
    )
    maintenance_content: str | None = Field(
        default=None, description="维护内容说明"
    )
    remark: str | None = Field(default=None, description="备注")


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
    responsible_person_id: uuid.UUID | None = Field(
        default=None, description="负责人ID"
    )
    maintenance_content: str | None = Field(
        default=None, description="维护内容说明"
    )
    status: MaintenancePlanStatus | None = Field(default=None, description="状态")
    remark: str | None = Field(default=None, description="备注")


class MaintenancePlanResponse(BaseModel):
    """维护计划响应"""

    id: uuid.UUID
    equipment_id: uuid.UUID
    plan_name: str
    plan_type: MaintenancePlanType
    frequency: int
    frequency_unit: FrequencyUnit
    last_maintenance_date: date | None
    next_maintenance_date: date | None
    responsible_person_id: uuid.UUID | None
    maintenance_content: str | None
    status: MaintenancePlanStatus
    remark: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}
