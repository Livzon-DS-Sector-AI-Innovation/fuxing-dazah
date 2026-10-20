"""特种设备遥测监控响应模型（facilities-p2）。

latest/history 票 01；rules/alarms/pending-reviews 随票 02/04 补齐。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TelemetryLatestItemOut(BaseModel):
    equipment_no: str
    metric: str
    value: float
    unit: str | None = None
    recorded_at: datetime
    parse_method: str


class TelemetryLatestOut(BaseModel):
    items: list[TelemetryLatestItemOut]


class TelemetryHistoryPointOut(BaseModel):
    ts: datetime
    value: float
    count: int


class TelemetryHistoryOut(BaseModel):
    equipment_no: str
    metric: str
    interval: str
    points: list[TelemetryHistoryPointOut]


class TelemetryAlarmAckIn(BaseModel):
    """值班确认入参（无必填字段，operator 取当前用户）。"""


class TelemetryAlarmResolveIn(BaseModel):
    """处置闭环入参：处置说明必填（闭环结论留痕）。"""

    note: str


class TelemetryPendingConfirmIn(BaseModel):
    """人工补录确认入参：设备编号 + 多指标 readings
    （metric/value 必填，recorded_at/unit 可选缺省原消息时间）。"""

    equipment_no: str
    readings: list[dict[str, Any]]
