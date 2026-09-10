"""消防报警 Schema — API 契约（ticket 02 同步；ticket 03 记录查询/统计；ticket 05 日报/周报生成）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class FireAlarmSyncResponse(BaseModel):
    """Bitable 全量同步结果。"""

    synced_count: int = Field(..., description="本次同步 upsert 的记录数")
    soft_deleted_count: int = Field(0, description="本次同步软删除的记录数")


class FireAlarmRecordOut(BaseModel):
    """报警记录列表项（含 AI 分析列）。"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    source: str
    alarm_time: datetime | None = None
    alarm_type: str | None = None
    department: str | None = None
    department_leader_name: str | None = None
    building: str | None = None
    location: str | None = None
    alarm_nature: str | None = None
    cause_category: str | None = None
    cause_description: str | None = None
    ai_dimension: str | None = None
    ai_reason_analysis: str | None = None
    ai_rectification_direction: str | None = None
    ai_analyzed_at: datetime | None = None
    synced_at: datetime | None = None
    created_at: datetime | None = None


class FireAlarmStatsOut(BaseModel):
    """KPI 卡数据（契约字段以 ticket 03 为准，分布为 dict 而非数组）。"""

    date: str  # 当日日期 ISO（target_date 或今天·北京时间）
    today_total: int = 0  # 今日报警数
    week_total: int = 0  # 本周（自然周 周一~周日·北京时间）报警数
    total_count: int = 0  # 全量报警数（非软删）
    week_ai_analyzed_count: int = 0  # 本周已 AI 分析的记录数
    nature_distribution: dict[str, int] = Field(default_factory=dict)  # 报警性质 → 数量
    type_distribution: dict[str, int] = Field(default_factory=dict)  # 报警类型 → 数量
    dimension_distribution: dict[str, int] = Field(default_factory=dict)  # AI 维度 → 数量
    department_distribution: dict[str, int] = Field(default_factory=dict)  # 部门 → 数量


class FireAlarmDailyReportRequest(BaseModel):
    """日报生成请求（ticket 05；API 端点在 ticket 07）。"""

    target_date: date | None = Field(None, description="目标日期，默认今天（北京时区）")


class FireAlarmWeeklyReportRequest(BaseModel):
    """周报生成请求（ticket 06；API 端点在 ticket 07）。"""

    week_end: date | None = Field(None, description="自然周末尾日期（周日），默认本周日或今天")


class FireAlarmReportResponse(BaseModel):
    """日报/周报生成结果（不落库，前端弹窗展示）。

    report_kind: "daily" / "weekly"
    target_date: 日报=当日；周报=周末日期
    week_start: 周报=周一（日报为 None）
    analyzed: 成功 AI 分析的记录数（仅日报）
    push_results: [{"chat_id", "success", "message_id"?, "skipped"?, "reason"?, "error"?}]
    records_analyzed: 已 AI 回写的记录 id（仅日报）
    """

    report_kind: str  # "daily" / "weekly"
    target_date: date  # 日报：当日；周报：周末日期
    week_start: date | None = None  # 周报：周一（日报为 None）
    total: int  # 涉及记录数
    analyzed: int = 0  # 成功 AI 分析的记录数（日报）
    markdown_report: str
    push_results: list[dict] = Field(default_factory=list)
    records_analyzed: list[uuid.UUID] = Field(default_factory=list)
