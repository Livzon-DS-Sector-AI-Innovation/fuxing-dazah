"""中控报警 Schema — API 契约（ticket 02 同步；ticket 03 查询/统计；ticket 05/06 日报生成）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CentralAlarmSyncResponse(BaseModel):
    """Bitable 多表全量同步结果。"""

    synced_count: int = Field(..., description="本次同步 upsert 的记录数")
    soft_deleted_count: int = Field(0, description="本次同步软删除的记录数")


class CentralAlarmRecordOut(BaseModel):
    """报警记录列表项（含 AI 分析列）。"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    source: str
    alarm_date: datetime | None = None
    post: str | None = None
    alarm_description: str | None = None
    special_note: str | None = None
    workshop: str | None = None
    line: str | None = None
    ai_alarm_type: str | None = None
    ai_equipment: str | None = None
    ai_pattern: str | None = None
    ai_dimension: str | None = None
    ai_reason_analysis: str | None = None
    ai_rectification_direction: str | None = None
    ai_analyzed_at: datetime | None = None
    synced_at: datetime | None = None
    created_at: datetime | None = None


class CentralAlarmStatsOut(BaseModel):
    """KPI 卡数据（分布为 dict 而非数组）。"""

    date: str  # 当日日期 ISO（target_date 或今天·北京时间）
    today_total: int = 0  # 今日报警数
    week_total: int = 0  # 本周（自然周 周一~周日·北京时间）报警数
    total_count: int = 0  # 全量报警数（非软删）
    week_ai_analyzed_count: int = 0  # 本周已 AI 分析的记录数
    workshop_distribution: dict[str, int] = Field(default_factory=dict)  # 车间 → 数量
    post_distribution: dict[str, int] = Field(default_factory=dict)  # 岗位 → 数量
    alarm_type_distribution: dict[str, int] = Field(default_factory=dict)  # 报警类型 → 数量
    pattern_distribution: dict[str, int] = Field(default_factory=dict)  # 异常模式 → 数量
    dimension_distribution: dict[str, int] = Field(default_factory=dict)  # AI 维度 → 数量


class CentralAlarmDailyReportRequest(BaseModel):
    """日报生成请求（ticket 06）。"""

    target_date: date | None = Field(None, description="目标日期，默认今天（北京时区）")


class CentralAlarmReportResponse(BaseModel):
    """日报生成结果（不落库，前端弹窗展示）。"""

    report_kind: str = "daily"
    target_date: date
    total: int = 0
    analyzed: int = 0
    markdown_report: str
    push_results: list[dict] = Field(default_factory=list)
    records_analyzed: list[uuid.UUID] = Field(default_factory=list)
