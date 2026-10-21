"""环境监测 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MONITOR_TYPES = Literal["settle", "float", "particle", "temp_humidity", "pressure"]


class EnvPointCreate(BaseModel):
    """监测点新增。"""

    room: str = Field(max_length=128, description="房间/区域")
    point_no: str = Field(max_length=64, description="点位编号")
    monitor_type: MONITOR_TYPES = Field(description="监测类型")
    frequency: Literal["per_batch", "weekly", "monthly"] | None = Field(default=None, description="监测频次")
    alert_limit: float | None = Field(default=None, ge=0, description="警戒限")
    action_limit: float | None = Field(default=None, ge=0, description="行动限")
    status: Literal["active", "inactive"] = Field(default="active", description="启用/停用")
    remark: str | None = Field(default=None, max_length=200)


class EnvPointUpdate(BaseModel):
    """监测点更新（全部可选）。"""

    room: str | None = Field(default=None, max_length=128)
    point_no: str | None = Field(default=None, max_length=64)
    monitor_type: MONITOR_TYPES | None = None
    frequency: Literal["per_batch", "weekly", "monthly"] | None = None
    alert_limit: float | None = Field(default=None, ge=0)
    action_limit: float | None = Field(default=None, ge=0)
    status: Literal["active", "inactive"] | None = None
    remark: str | None = Field(default=None, max_length=200)


class EnvPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room: str
    point_no: str
    monitor_type: str
    frequency: str | None
    alert_limit: float | None
    action_limit: float | None
    status: str
    remark: str | None
    created_at: datetime


class EnvRecordCreate(BaseModel):
    """监测记录填报：按点位的警戒限/行动限自动判定三态。"""

    point_id: uuid.UUID = Field(description="监测点")
    record_date: str = Field(max_length=32, description="监测日期 YYYY-MM-DD")
    result_value: float | None = Field(default=None, ge=0, description="检测结果值")
    remark: str | None = Field(default=None, max_length=200)


class EnvRecordOut(BaseModel):
    id: uuid.UUID
    point_id: uuid.UUID
    room: str
    point_no: str
    monitor_type: str
    record_date: str
    result_value: float | None
    alert_limit: float | None
    action_limit: float | None
    judge: str | None
    recorded_by: uuid.UUID | None
    recorded_by_name: str | None
    remark: str | None
    created_at: datetime
