"""Energy request and response schemas live here."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

StrUUID = Annotated[str, BeforeValidator(str)]
EnergyType = Literal["electricity", "water", "gas"]
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
    workshop: str = Field(..., min_length=1, max_length=100, description="所属车间")
    production_line: str | None = Field(
        default=None, max_length=100, description="所属产线"
    )
    monitor_level: MonitorLevel = Field(default="normal", description="监控等级")
    unit: str = Field(..., min_length=1, max_length=20, description="计量单位")
    collection_interval: int = Field(default=60, ge=1, description="采集间隔(分钟)")
    is_enabled: bool = Field(default=True, description="是否启用采集")
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
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    collection_interval: int | None = Field(default=None, ge=1)
    is_enabled: bool | None = Field(default=None)
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
    is_enabled: bool
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


class EnergyStatisticsResponse(BaseModel):
    group_key: str = Field(description="分组键(车间/产线/设备名)")
    total_value: float = Field(description="能耗合计")
    unit: str = Field(description="计量单位")
    data_count: int = Field(description="数据条数")


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


class CollectLogDeviceDetail(BaseModel):
    """采集日志中单个设备的数据详情"""

    device_name: str = Field(description="设备名称")
    platform_device_code: str = Field(description="平台设备编码")
    energy_type: str = Field(description="能源类型")
    value: float = Field(description="采集值")
    unit: str = Field(description="计量单位")
    data_timestamp: datetime = Field(description="数据时间点")


class CollectLogDetailResponse(BaseModel):
    """采集日志详情响应"""

    id: StrUUID
    platform_code: str
    collect_time: datetime
    status: str
    device_count: int
    success_count: int
    error_message: str | None
    created_at: datetime
    devices: list[CollectLogDeviceDetail] = Field(
        default_factory=list, description="设备数据详情列表"
    )
    time_range_start: datetime | None = Field(
        default=None, description="数据覆盖起始时间"
    )
    time_range_end: datetime | None = Field(
        default=None, description="数据覆盖结束时间"
    )


class CollectTriggerRequest(BaseModel):
    platform_code: str | None = Field(
        default=None,
        description="指定平台，为空则采集所有平台",
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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnergyAlertRecordResponse(BaseModel):
    id: StrUUID
    rule_id: StrUUID
    device_config_id: StrUUID | None
    energy_type: str
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
