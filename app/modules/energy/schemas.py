"""Energy request and response schemas live here."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

StrUUID = Annotated[str, BeforeValidator(str)]
EnergyType = Literal["electricity", "steam", "water"]
MonitorLevel = Literal["normal", "important", "urgent"]
CollectStatus = Literal["success", "partial", "failed"]


class EnergyDeviceConfigCreate(BaseModel):
    platform_code: str = Field(..., min_length=1, max_length=50, description="平台标识")
    platform_device_code: str = Field(
        ..., min_length=1, max_length=100, description="三方平台设备编码"
    )
    device_name: str = Field(..., min_length=1, max_length=200, description="设备名称")
    energy_type: EnergyType = Field(..., description="能源类型")
    api_endpoint: str = Field(..., min_length=1, max_length=500, description="API 路径")
    workshop: str = Field(..., min_length=1, max_length=100, description="所属车间")
    production_line: str = Field(
        ..., min_length=1, max_length=100, description="所属产线"
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
    api_endpoint: str | None = Field(default=None, min_length=1, max_length=500)
    workshop: str | None = Field(default=None, min_length=1, max_length=100)
    production_line: str | None = Field(default=None, min_length=1, max_length=100)
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
    production_line: str
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


class CollectTriggerRequest(BaseModel):
    platform_code: str | None = Field(
        default=None,
        description="指定平台，为空则采集所有平台",
    )
