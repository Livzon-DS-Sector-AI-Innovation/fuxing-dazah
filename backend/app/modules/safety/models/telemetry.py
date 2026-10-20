"""特种设备遥测监控 ORM（facilities-p2，DESIGN §3.2 表 4/5）。

- TelemetrySnapshot：群消息统计整理的时序快照。唯一 (equipment_no, metric,
  recorded_at) = 幂等落库核心（PG 唯一索引对 NULL 不去重——pending_review 行
  设备/指标可空，正好走非幂等路径由 raw_message_id 防重）。
- TelemetryAlarmRecord：规则命中产生的报警记录。dedupe_key =
  设备|指标|级别|静默窗时间桶，唯一约束天然实现「同窗同源不重发」；跨窗
  自然放行新报警（静默窗口默认 30 分钟，SAFETY_TELEMETRY_SILENCE_SECONDS）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

PARSE_METHOD_TEMPLATE = "template"
PARSE_METHOD_AI = "ai"
PARSE_METHOD_MANUAL = "manual"

PARSE_STATUS_OK = "ok"
PARSE_STATUS_PENDING_REVIEW = "pending_review"

ALARM_LEVEL_WARNING = "warning"
ALARM_LEVEL_ALARM = "alarm"

ALARM_STATUS_FIRING = "firing"
ALARM_STATUS_ACKED = "acked"
ALARM_STATUS_RESOLVED = "resolved"


class TelemetrySnapshot(BaseModel):
    """遥测时序快照（趋势图与规则判定的直接数据源）。"""

    __tablename__ = "telemetry_snapshots"
    __table_args__ = (
        Index(
            "uq_telemetry_snapshots_eq_metric_at",
            "equipment_no", "metric", "recorded_at",
            unique=True,
        ),
        Index("ix_telemetry_snapshots_raw_message", "raw_message_id"),
        {"schema": "safety"},
    )

    equipment_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="设备编号（pending_review 待归属行可空）"
    )
    metric: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="指标名（汽压/水位/炉膛温度…；待补录行可空）"
    )
    value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="读数值（解析失败行可空，人工补录后回填）"
    )
    unit: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="单位（MPa/mm/℃…）"
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="读数时间（消息 create_time 或人工指定）"
    )

    raw_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="来源群消息 message_id（溯源回群）"
    )
    parse_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PARSE_METHOD_TEMPLATE,
        server_default=PARSE_METHOD_TEMPLATE,
        comment="解析方式：template / ai / manual",
    )
    raw_excerpt: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="原消息文本摘录（待补录列表展示）"
    )
    parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PARSE_STATUS_OK,
        server_default=PARSE_STATUS_OK,
        comment="ok / pending_review（解析失败待人工补录）",
    )


class TelemetryAlarmRecord(BaseModel):
    """遥测报警记录（firing → acked → resolved 处置闭环）。"""

    __tablename__ = "telemetry_alarm_records"
    __table_args__ = (
        Index("uq_telemetry_alarm_dedupe", "dedupe_key", unique=True),
        Index("ix_telemetry_alarm_status", "status"),
        Index("ix_telemetry_alarm_equipment", "equipment_no"),
        {"schema": "safety"},
    )

    equipment_no: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="触发时读数")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="触发读数的快照时间"
    )
    rule_desc: Mapped[str] = mapped_column(
        Text, nullable=False, comment="命中规则的人读描述（如「汽压超上限 1.0MPa」）"
    )
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="warning / alarm",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ALARM_STATUS_FIRING,
        server_default=ALARM_STATUS_FIRING,
        comment="firing / acked / resolved",
    )

    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="值班确认人（open_id / system）"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处置说明（resolved 必填）"
    )
    dedupe_key: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="设备|指标|级别|静默窗时间桶（同窗同源唯一，防刷屏）",
    )
