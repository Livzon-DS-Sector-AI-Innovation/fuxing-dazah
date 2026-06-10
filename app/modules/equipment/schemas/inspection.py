"""Inspection schemas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── 枚举 ──
InspectionPeriodType = Literal["每日", "每周", "每月", "专项"]
InspectionTaskStatus = Literal["待执行", "执行中", "已完成", "已关闭"]
InspectionPlanType = Literal["线路巡检", "设备巡检"]
InspectionOverallResult = Literal["正常", "异常"]
CheckResult = Literal["正常", "异常", "跳过"]


# ═══════════ 巡检路线 ═══════════
class InspectionRouteCreate(BaseModel):
    """创建巡检路线请求"""

    name: str = Field(..., max_length=200, description="路线名称")
    description: str | None = Field(default=None, description="路线描述")
    area: str | None = Field(default=None, max_length=100, description="区域")
    period_type: InspectionPeriodType = Field(
        default="每日", description="巡检周期类型"
    )
    period_value: int | None = Field(
        default=None, ge=1, description="周期数值"
    )
    template_id: uuid.UUID | None = Field(
        default=None, description="默认检查模板ID"
    )


class InspectionRouteUpdate(BaseModel):
    """更新巡检路线请求"""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None)
    area: str | None = Field(default=None, max_length=100)
    is_active: bool | None = Field(default=None)
    period_type: InspectionPeriodType | None = Field(default=None)
    period_value: int | None = Field(default=None)
    template_id: uuid.UUID | None = Field(default=None)


class InspectionRouteEquipmentItem(BaseModel):
    """路线设备配置项"""

    equipment_id: uuid.UUID = Field(..., description="设备ID")
    sort_order: int = Field(default=0, description="排序")


class InspectionRouteEquipmentBatch(BaseModel):
    """批量设置路线设备请求"""

    equipments: list[InspectionRouteEquipmentItem] = Field(
        ..., min_length=1, description="设备列表"
    )


class RouteEquipmentResponse(BaseModel):
    """路线设备关联响应"""

    id: uuid.UUID
    equipment_id: uuid.UUID
    sort_order: int
    equipment_name: str | None = None
    equipment_no: str | None = None

    model_config = {"from_attributes": True}


class InspectionRouteResponse(BaseModel):
    """巡检路线响应"""

    id: uuid.UUID
    name: str
    description: str | None
    area: str | None
    is_active: bool
    period_type: InspectionPeriodType
    period_value: int | None
    template_id: uuid.UUID | None
    equipment_count: int = 0
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class InspectionRouteDetailResponse(InspectionRouteResponse):
    """巡检路线详情响应（含设备列表）"""

    equipments: list[RouteEquipmentResponse] = Field(default_factory=list)


# ═══════════ 巡检任务 ═══════════
class InspectionTaskCreate(BaseModel):
    """创建巡检任务请求"""

    route_id: uuid.UUID | None = Field(default=None, description="路线ID")
    equipment_id: uuid.UUID | None = Field(
        default=None, description="单设备ID（兼容旧版，推荐用 equipment_ids）"
    )
    equipment_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, description="设备ID列表（多设备模式）"
    )
    template_id: uuid.UUID | None = Field(
        default=None, description="检查模板ID（线路巡检时可选，从路线默认模板获取）"
    )
    plan_type: InspectionPlanType = Field(
        default="设备巡检", description="巡检类型"
    )
    assigned_to: uuid.UUID | None = Field(
        default=None, description="巡检人员ID"
    )
    planned_date: date = Field(..., description="计划日期")


class InspectionTaskUpdate(BaseModel):
    """更新巡检任务请求"""

    assigned_to: uuid.UUID | None = Field(default=None)
    planned_date: date | None = Field(default=None)


class InspectionTaskClose(BaseModel):
    """关闭任务请求"""

    closure_remark: str | None = Field(default=None, description="关闭备注")


class InspectionTaskResponse(BaseModel):
    """巡检任务响应"""

    id: uuid.UUID
    task_no: str
    route_id: uuid.UUID | None
    equipment_id: uuid.UUID | None
    equipment_ids: list[uuid.UUID] | None = None
    template_id: uuid.UUID
    plan_type: InspectionPlanType
    assigned_to: uuid.UUID | None
    planned_date: date
    status: InspectionTaskStatus
    overall_result: InspectionOverallResult | None
    started_at: datetime | None
    completed_at: datetime | None
    closed_at: datetime | None
    closure_remark: str | None
    route_summary: str | None = None
    created_at: datetime
    updated_at: datetime
    route_name: str | None = None
    equipment_name: str | None = None
    equipment_no: str | None = None
    template_name: str | None = None
    assignee_name: str | None = None
    equipment_count: int = 0
    completed_count: int = 0
    photo_count: int = 0

    model_config = {"from_attributes": True}


# ═══════════ 巡检执行 ═══════════
class InspectionRecordItem(BaseModel):
    """单条检查项结果"""

    template_item_id: uuid.UUID = Field(..., description="检查项ID")
    result: CheckResult = Field(..., description="结果：正常/异常/跳过")
    actual_value: str | None = Field(default=None, description="实际值")
    remark: str | None = Field(default=None, description="备注")


class EquipmentCheckResult(BaseModel):
    """单设备检查结果（含多个检查项）"""

    records: list[InspectionRecordItem] = Field(
        ..., min_length=1, description="检查项结果列表"
    )


class InspectionRecordResponse(BaseModel):
    """巡检记录响应"""

    id: uuid.UUID
    task_id: uuid.UUID
    equipment_id: uuid.UUID | None = None
    equipment_name: str | None = None
    template_item_id: uuid.UUID
    result: str
    actual_value: str | None
    remark: str | None
    item_name: str | None = None
    expected_result: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════ 线路巡检提交 ═══════════
class RouteCheckSubmit(BaseModel):
    """线路巡检提交请求"""

    overall_result: InspectionOverallResult = Field(
        ..., description="总体结果：正常/异常"
    )
    route_summary: str | None = Field(
        default=None, description="现场描述"
    )


# ═══════════ 巡检照片 ═══════════
class InspectionPhotoResponse(BaseModel):
    """巡检照片响应"""

    id: uuid.UUID
    task_id: uuid.UUID
    equipment_id: uuid.UUID | None = None
    file_name: str
    file_size: int | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# ═══════════ AI 分析 ═══════════
class InspectionAIAnalyzeRequest(BaseModel):
    """AI 分析请求"""

    image_base64: str = Field(..., description="图片的 base64 编码")
    image_mime_type: str = Field(
        default="image/jpeg", description="图片 MIME 类型"
    )


class InspectionAIItemResult(BaseModel):
    """单检查项 AI 分析结果"""

    template_item_id: uuid.UUID = Field(..., description="检查项ID")
    item_name: str = Field(..., description="检查项名称")
    expected_result: str | None = Field(default=None, description="预期结果")
    result: str = Field(..., description="结果：正常/异常/跳过")
    actual_value: str | None = Field(default=None, description="实际值")
    remark: str | None = Field(default=None, description="备注")


class InspectionAIAnalyzeResponse(BaseModel):
    """AI 分析响应"""

    items: list[InspectionAIItemResult] = Field(
        default_factory=list, description="分析结果列表"
    )


# ═══════════ 历史详情 ═══════════
class InspectionTaskDetailResponse(InspectionTaskResponse):
    """巡检任务详情响应（含记录和照片）"""

    records: list[InspectionRecordResponse] = Field(default_factory=list)
    photos: list[InspectionPhotoResponse] = Field(default_factory=list)
