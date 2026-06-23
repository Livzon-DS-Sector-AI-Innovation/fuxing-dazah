"""Inspection schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── 枚举 ──
InspectionTaskStatus = Literal["待执行", "执行中", "已完成", "已关闭"]
InspectionPlanType = Literal["线路巡检", "设备巡检"]
InspectionOverallResult = Literal["正常", "异常"]
CheckResult = Literal["正常", "异常", "跳过"]


# ═══════════ 巡检路线 ═══════════
class InspectionRouteCreate(BaseModel):
    """创建巡检路线请求"""

    name: str = Field(..., max_length=200, description="路线名称")
    description: str | None = Field(default=None, description="路线描述")
class InspectionRouteUpdate(BaseModel):
    """更新巡检路线请求"""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class InspectionRouteResponse(BaseModel):
    """巡检路线响应"""

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    equipment_count: int = 0
    location_count: int = 0
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class InspectionRouteDetailResponse(InspectionRouteResponse):
    """巡检路线详情响应（含地点设备列表）"""

    locations: list["RouteLocationResponse"] = Field(default_factory=list)


# ═══════════ 线路地点配置 ═══════════
class RouteLocationEquipmentItem(BaseModel):
    """地点设备配置请求项"""

    equipment_id: uuid.UUID = Field(..., description="设备ID")
    sort_order: int = Field(default=0, description="排序")
    template_ids: list[uuid.UUID] = Field(
        default_factory=list, description="绑定的模板ID列表"
    )


class RouteLocationItem(BaseModel):
    """线路地点配置请求项"""

    location_id: uuid.UUID = Field(..., description="地点ID")
    sort_order: int = Field(default=0, description="地点顺序")
    equipments: list[RouteLocationEquipmentItem] = Field(
        default_factory=list, description="该地点下的设备列表"
    )


class RouteLocationsBatch(BaseModel):
    """批量设置线路地点-设备-模板请求"""

    locations: list[RouteLocationItem] = Field(
        default_factory=list, description="地点列表（全量替换）"
    )


class RouteEquipmentTemplateResponse(BaseModel):
    """设备-模板绑定响应"""

    id: uuid.UUID
    template_id: uuid.UUID
    template_name: str | None = None

    model_config = {"from_attributes": True}


class RouteLocationEquipmentResponse(BaseModel):
    """线路地点设备响应"""

    id: uuid.UUID
    equipment_id: uuid.UUID
    sort_order: int
    equipment_name: str | None = None
    equipment_no: str | None = None
    templates: list[RouteEquipmentTemplateResponse] = Field(
        default_factory=list
    )

    model_config = {"from_attributes": True}


class RouteLocationResponse(BaseModel):
    """线路地点响应"""

    id: uuid.UUID
    location_id: uuid.UUID
    location_name: str | None = None
    sort_order: int
    equipments: list[RouteLocationEquipmentResponse] = Field(
        default_factory=list
    )

    model_config = {"from_attributes": True}


# ═══════════ 保留旧 schemas（不可删除，可能被其他代码引用） ═══════════
class InspectionRouteEquipmentItem(BaseModel):
    """路线设备配置项（已废弃，保留兼容）"""

    equipment_id: uuid.UUID = Field(..., description="设备ID")
    sort_order: int = Field(default=0, description="排序")


class InspectionRouteEquipmentBatch(BaseModel):
    """批量设置路线设备请求（已废弃，保留兼容）"""

    equipments: list[InspectionRouteEquipmentItem] = Field(
        ..., min_length=1, description="设备列表"
    )


class RouteEquipmentResponse(BaseModel):
    """路线设备关联响应（已废弃，保留兼容）"""

    id: uuid.UUID
    equipment_id: uuid.UUID
    sort_order: int
    equipment_name: str | None = None
    equipment_no: str | None = None

    model_config = {"from_attributes": True}


# ═══════════ 巡检路线定时任务 ═══════════
class InspectionScheduleCreate(BaseModel):
    """创建定时任务请求"""

    cron_expression: str = Field(..., max_length=50, description="cron 表达式")
    assigned_to: uuid.UUID = Field(..., description="巡检人员ID")
    is_active: bool = Field(default=True, description="是否启用")


class InspectionScheduleUpdate(BaseModel):
    """更新定时任务请求"""

    cron_expression: str | None = Field(default=None, max_length=50)
    assigned_to: uuid.UUID | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class InspectionScheduleResponse(BaseModel):
    """定时任务响应"""

    id: uuid.UUID
    route_id: uuid.UUID
    cron_expression: str
    assigned_to: uuid.UUID | None
    is_active: bool
    last_triggered_at: datetime | None
    next_trigger_at: datetime | None
    assignee_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    template_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, description="[DEPRECATED] 模板ID列表，推荐用 equipment_templates"
    )
    equipment_templates: dict[str, list[uuid.UUID]] | None = Field(
        default=None, description="设备-模板映射（设备巡检用）: {equipment_id: [template_id, ...]}"
    )
    plan_type: InspectionPlanType = Field(
        default="设备巡检", description="巡检类型"
    )
    assigned_to: uuid.UUID | None = Field(
        default=None, description="巡检人员ID"
    )
    planned_time: datetime = Field(..., description="计划巡检时间")


class InspectionTaskUpdate(BaseModel):
    """更新巡检任务请求"""

    assigned_to: uuid.UUID | None = Field(default=None)
    planned_time: datetime | None = Field(default=None)


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
    template_ids: list[uuid.UUID] | None = None
    equipment_templates: dict[str, list[uuid.UUID]] | None = None
    plan_type: InspectionPlanType
    assigned_to: uuid.UUID | None
    planned_time: datetime
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
    assignee_name: str | None = None
    equipment_count: int = 0
    completed_count: int = 0
    completed_equipment_ids: list[uuid.UUID] = []
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
    route_location_id: uuid.UUID | None = None

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
