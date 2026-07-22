"""Energy request and response schemas live here."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

StrUUID = Annotated[str, BeforeValidator(str)]
EnergyType = Literal["electricity", "water", "steam", "cooling", "compressed_air", "nitrogen", "natural_gas"]
MonitorLevel = Literal["normal", "important", "urgent"]
CollectStatus = Literal["success", "partial", "failed"]


class EnergyDeviceConfigCreate(BaseModel):
    platform_code: str = Field(..., min_length=1, max_length=50, description="平台标识")
    platform_device_code: str = Field(
        ..., min_length=1, max_length=100, description="三方平台设备编码"
    )
    device_name: str = Field(..., min_length=1, max_length=200, description="设备名称")
    energy_type: EnergyType = Field(..., description="能源类型")
    api_endpoint: str = Field(default="", max_length=500, description="API 路径")
    workshop: str = Field(..., min_length=1, max_length=100, description="所属部门")
    production_line: str | None = Field(
        default=None, max_length=100, description="所属区域"
    )
    monitor_level: MonitorLevel = Field(default="normal", description="监控等级")
    collection_interval: int = Field(default=60, ge=1, description="采集间隔(分钟)")
    daily_collect_time: str | None = Field(
        default=None, pattern=r"^\d{2}:\d{2}$", max_length=5, description="按天采集触发时间 HH:MM，如 08:00"
    )
    is_enabled: bool = Field(default=True, description="是否启用采集")
    equipment_id: str | None = Field(default=None, description="关联设备管理中的设备ID")
    equipment_name: str | None = Field(default=None, max_length=200, description="关联设备名称")
    remark: str | None = Field(default=None, max_length=500, description="备注")


class EnergyDeviceConfigUpdate(BaseModel):
    platform_code: str | None = Field(default=None, min_length=1, max_length=50)
    platform_device_code: str | None = Field(default=None, min_length=1, max_length=100)
    device_name: str | None = Field(default=None, min_length=1, max_length=200)
    energy_type: EnergyType | None = Field(default=None)
    api_endpoint: str = Field(default="", max_length=500)
    workshop: str | None = Field(default=None, min_length=1, max_length=100)
    production_line: str | None = Field(default=None, max_length=100)
    monitor_level: MonitorLevel | None = Field(default=None)
    collection_interval: int | None = Field(default=None, ge=1)
    daily_collect_time: str | None = Field(
        default=None, pattern=r"^\d{2}:\d{2}$", max_length=5, description="按天采集触发时间 HH:MM"
    )
    is_enabled: bool | None = Field(default=None)
    equipment_id: str | None = Field(default=None, description="关联设备管理中的设备ID")
    equipment_name: str | None = Field(default=None, max_length=200, description="关联设备名称")
    remark: str | None = Field(default=None, max_length=500)


class EnergyDeviceConfigResponse(BaseModel):
    id: StrUUID
    platform_code: str
    platform_device_code: str
    device_name: str
    energy_type: str
    api_endpoint: str
    workshop: str
    production_line: str | None
    monitor_level: str
    unit: str
    collection_interval: int
    daily_collect_time: str | None
    is_enabled: bool
    equipment_id: str | None
    equipment_name: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnergyDataResponse(BaseModel):
    id: StrUUID
    device_config_id: StrUUID
    timestamp: datetime
    value: float
    unit: str
    collected_at: datetime

    model_config = {"from_attributes": True}


class EnergyDataDeleteRequest(BaseModel):
    """批量删除能耗数据请求"""
    ids: list[StrUUID] = Field(..., min_length=1, max_length=200, description="能耗数据ID列表")


class CollectLogResponse(BaseModel):
    id: StrUUID
    platform_code: str
    collect_time: datetime
    status: str
    device_count: int
    success_count: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CollectTriggerRequest(BaseModel):
    platform_code: str | None = Field(
        default=None,
        description="指定平台，为空则采集所有平台",
    )


class CollectSettingsResponse(BaseModel):
    """自动采集运行时设置"""
    auto_collect_enabled: bool = Field(description="是否启用自动采集")
    auto_collect_interval_seconds: int = Field(description="自动采集间隔（秒），范围 3600~86400（1h~24h）")


class CollectSettingsUpdate(BaseModel):
    """更新自动采集运行时设置"""
    auto_collect_enabled: bool | None = Field(default=None, description="是否启用自动采集")
    auto_collect_interval_seconds: int | None = Field(
        default=None, ge=3600, le=86400, description="自动采集间隔（秒），最小 3600（1h），最大 86400（24h）"
    )


# ── 预警系统 ──

AlertLevel = Literal["info", "warning", "critical", "emergency"]
MonitorMetric = Literal["instant", "daily_total", "monthly_total"]
ThresholdType = Literal["greater_than", "less_than", "equal"]
NotifyFrequency = Literal["first", "every", "daily_summary"]
EffectiveTime = Literal["all_day", "custom"]
AlertRecordStatus = Literal["pending", "processed", "ignored"]


class EnergyAlertRuleCreate(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=200, description="规则名称")
    rule_description: str | None = Field(
        default=None, max_length=500, description="规则描述"
    )
    energy_type: EnergyType = Field(..., description="能源类型")
    monitor_metric: MonitorMetric = Field(..., description="监控指标")
    threshold_type: ThresholdType = Field(..., description="阈值类型")
    threshold_value: float = Field(..., gt=0, description="阈值")
    unit: str = Field(..., min_length=1, max_length=20, description="计量单位")
    alert_level: AlertLevel = Field(..., description="预警等级")
    notify_method: list[str] = Field(..., min_length=1, description="通知方式")
    notify_users: list[str] = Field(..., min_length=1, description="通知用户列表")
    notify_frequency: NotifyFrequency = Field(default="first", description="通知频率")
    effective_time: EffectiveTime = Field(default="all_day", description="生效时段类型")
    custom_time_start: str | None = Field(default=None, description="自定义开始时间")
    custom_time_end: str | None = Field(default=None, description="自定义结束时间")
    is_enabled: bool = Field(default=True, description="是否启用")
    workshop: str | None = Field(
        default=None, max_length=100, description="关联车间（系统规则按车间绑定）"
    )


class EnergyAlertRuleUpdate(BaseModel):
    rule_name: str | None = Field(default=None, min_length=1, max_length=200)
    rule_description: str | None = Field(default=None, max_length=500)
    energy_type: EnergyType | None = Field(default=None)
    monitor_metric: MonitorMetric | None = Field(default=None)
    threshold_type: ThresholdType | None = Field(default=None)
    threshold_value: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    alert_level: AlertLevel | None = Field(default=None)
    notify_method: list[str] | None = Field(default=None, min_length=1)
    notify_users: list[str] | None = Field(default=None, min_length=1)
    notify_frequency: NotifyFrequency | None = Field(default=None)
    effective_time: EffectiveTime | None = Field(default=None)
    custom_time_start: str | None = Field(default=None)
    custom_time_end: str | None = Field(default=None)
    is_enabled: bool | None = Field(default=None)


class EnergyAlertRuleResponse(BaseModel):
    id: StrUUID
    rule_name: str
    rule_description: str | None
    energy_type: str
    monitor_metric: str
    threshold_type: str
    threshold_value: float
    unit: str
    alert_level: str
    notify_method: list[str]
    notify_users: list[str]
    notify_frequency: str
    effective_time: str
    custom_time_start: str | None
    custom_time_end: str | None
    is_enabled: bool
    workshop: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnergyAlertRecordResponse(BaseModel):
    id: StrUUID
    rule_id: StrUUID
    device_config_id: StrUUID | None
    energy_type: str
    workshop: str | None
    alert_level: str
    trigger_value: float
    threshold_value: float
    unit: str
    alert_time: datetime
    status: str
    processed_by: str | None
    processed_at: datetime | None
    process_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertRecordProcessRequest(BaseModel):
    status: Literal["processed", "ignored"] = Field(..., description="处理结果")
    process_note: str | None = Field(
        default=None, max_length=500, description="处理备注"
    )


# ── 车间预警配置 ──


class EnergyWorkshopConfigCreate(BaseModel):
    """创建车间预警配置"""
    workshop: str = Field(..., min_length=1, max_length=100, description="车间名称")
    heads: list[dict[str, str]] = Field(
        default_factory=list,
        description='负责人列表 JSON: [{"name": "张三", "feishu_open_id": "ou_xxx"}]',
    )
    auto_notify_enabled: bool = Field(default=True, description="是否启用自动预警通知")
    is_enabled: bool = Field(default=True, description="是否启用该车间配置")


class EnergyWorkshopConfigUpdate(BaseModel):
    """更新车间预警配置"""
    workshop: str | None = Field(default=None, min_length=1, max_length=100, description="车间名称")
    heads: list[dict[str, str]] | None = Field(default=None, description="负责人列表")
    auto_notify_enabled: bool | None = Field(default=None, description="是否启用自动预警通知")
    is_enabled: bool | None = Field(default=None, description="是否启用该车间配置")


class EnergyWorkshopConfigResponse(BaseModel):
    id: StrUUID
    workshop: str
    heads: list[dict[str, str]]
    auto_notify_enabled: bool
    is_enabled: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonnelCandidate(BaseModel):
    """负责人候选人（从 identity.users 查询，供前端下拉多选）。"""
    name: str
    feishu_open_id: str
    department: str | None = None


# ── 能源类型可视化配置 ──


class EnergyTypeConfigCreate(BaseModel):
    """创建能源类型配置"""
    type_code: str = Field(..., min_length=1, max_length=50, description="唯一编码")
    parent_code: str | None = Field(default=None, max_length=50, description="父级编码")
    display_name: str = Field(..., min_length=1, max_length=100, description="展示名称")
    unit: str = Field(..., min_length=1, max_length=20, description="计量单位")
    sort_order: int = Field(default=0, description="排序权重")
    is_enabled: bool = Field(default=True, description="是否启用")
    color: str | None = Field(default=None, max_length=20, description="卡片颜色")
    remark: str | None = Field(default=None, max_length=500, description="备注")


class EnergyTypeConfigUpdate(BaseModel):
    """更新能源类型配置（type_code 不可改）"""
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    sort_order: int | None = Field(default=None)
    is_enabled: bool | None = Field(default=None)
    parent_code: str | None = Field(default=None, max_length=50)
    remark: str | None = Field(default=None, max_length=500)


class EnergyTypeConfigResponse(BaseModel):
    id: StrUUID
    type_code: str
    parent_code: str | None
    display_name: str
    unit: str
    icon: str | None
    color: str | None
    sort_order: int
    is_enabled: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
