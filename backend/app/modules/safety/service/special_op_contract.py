# 特殊作业记录的结构化协议（Protocol）。
#
# 日报风险判定、AI 分析、Markdown 渲染三处消费方只依赖下面这组属性，因此既可以被
# 平台库 ORM 模型满足，也可以被直读路径的轻量视图对象满足，换数据源时这三处规则无需改动。

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Protocol


class SpecialOpRecord(Protocol):
    # 判定 / AI 分析 / 渲染共同依赖的最小属性集（结构化类型）。

    id: uuid.UUID
    created_at: datetime

    source: str
    feishu_record_id: str | None

    operation_type: str
    work_description: str | None
    location: str | None
    department: str | None
    personnel_type: str | None
    work_duration_hours: float | None

    planned_start_time: datetime | None
    planned_end_time: datetime | None
    submitted_at: datetime | None

    risk_level: str | None
    daily_risk_level: str | None
    daily_risk_reason: str | None
    inferred_operation_types: list[Any] | None
    is_excluded: bool
    exclusion_reason: str | None
    daily_report_date: date | None

    fire_work_method: str | None
    height_work_method: str | None
    work_height: float | None
    lifting_weight: float | None
    contractor_name: str | None

    is_weekend_holiday: str | None
    is_national_holiday: str | None
    other_operation_types: list[Any] | None
