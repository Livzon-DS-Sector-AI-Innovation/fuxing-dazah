"""设备状态日志与时间开动率 schemas。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EquipmentStatusLogItem(BaseModel):
    """状态变更历史条目"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    log_type: str = Field(description="日志类型：status(设备状态)/running(运行状态)")
    old_status: str | None = None
    new_status: str
    changed_at: datetime
    source: str


class AvailabilityItem(BaseModel):
    """单台设备的时间开动率"""

    equipment_id: uuid.UUID
    equipment_no: str
    name: str
    current_status: str
    current_running_status: str
    status_hours: dict[str, float] = Field(
        default_factory=dict, description="范围内开机/停机时长（小时）"
    )
    available_hours: float = Field(description="开机时长（小时）")
    total_hours: float = Field(description="统计分母时长（小时），即有运行记录的日历时长")
    availability_rate: float | None = Field(
        default=None, description="时间开动率 = 开机/分母；无有效时长时为空"
    )


class AvailabilityResponse(BaseModel):
    """时间开动率统计响应"""

    from_date: date
    to_date: date
    overall_rate: float | None = Field(default=None, description="整体开动率")
    items: list[AvailabilityItem]
