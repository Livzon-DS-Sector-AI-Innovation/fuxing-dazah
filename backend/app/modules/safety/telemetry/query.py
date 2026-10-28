"""快照查询：latest（实时读数卡）与 history（趋势序列）（facilities-p2 票 01）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    PARSE_STATUS_OK,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)

_INTERVALS = {"hour", "day"}

_ALARM_STATUSES = {"firing", "acked", "resolved"}


def _ok_conditions() -> list[ColumnElement[bool]]:
    """读数卡/趋势只看有效行：非软删 + ok + 设备/指标/数值齐全。"""
    return [
        TelemetrySnapshot.is_deleted.is_(False),
        TelemetrySnapshot.parse_status == PARSE_STATUS_OK,
        TelemetrySnapshot.equipment_no.is_not(None),
        TelemetrySnapshot.metric.is_not(None),
        TelemetrySnapshot.value.is_not(None),
    ]


async def latest_values(
    db: AsyncSession,
    *,
    equipment_no: str | None = None,
    rules: tuple | None = None,
    category_by_equipment: dict[str, str] | None = None,
) -> list[dict]:
    """每设备每指标最新一条读数（DISTINCT ON，按设备/指标/时间序稳定输出）。

    status=按当前生效规则对**单点最新值**的越界着色（normal/warning/alarm）：
    读数卡状态色口径；与报警判定（连续 N 点去抖）是两个口径，这里不去抖——
    最新值越界即标色提示，是否成报警由规则引擎判。类别缺失按「锅炉」兜底
    （采集源即锅炉群，与 collector 判定同口径）。
    """
    from app.modules.safety.telemetry.rules import rule_for

    if rules is None:
        from app.modules.safety.app_config.store import store
        from app.modules.safety.telemetry.rules import effective_rules

        rules = effective_rules(store.get_str("SAFETY_TELEMETRY_RULES") or None)

    stmt = (
        select(TelemetrySnapshot)
        .where(*_ok_conditions())
        .distinct(TelemetrySnapshot.equipment_no, TelemetrySnapshot.metric)
        .order_by(
            TelemetrySnapshot.equipment_no,
            TelemetrySnapshot.metric,
            TelemetrySnapshot.recorded_at.desc(),
        )
    )
    if equipment_no:
        stmt = stmt.where(TelemetrySnapshot.equipment_no == equipment_no)
    rows = (await db.execute(stmt)).scalars().all()

    def _status(row: TelemetrySnapshot) -> str:
        from app.modules.safety.facilities.engine import category_label

        raw = (category_by_equipment or {}).get(row.equipment_no or "") or "锅炉"
        rule = rule_for(rules, row.equipment_no, category_label(raw), row.metric)
        if rule is None:
            return "normal"
        if rule.max is not None and row.value > rule.max:
            return rule.level
        if rule.min is not None and row.value < rule.min:
            return rule.level
        return "normal"

    return [
        {
            "equipment_no": r.equipment_no,
            "metric": r.metric,
            "value": r.value,
            "unit": r.unit,
            "recorded_at": r.recorded_at,
            "parse_method": r.parse_method,
            "status": _status(r),
        }
        for r in rows
    ]


async def history_series(
    db: AsyncSession,
    equipment_no: str,
    metric: str,
    *,
    from_: datetime,
    to: datetime,
    interval: str = "hour",
) -> list[dict]:
    """按小时/日桶聚合的趋势序列（桶内均值 + 点数，空桶缺席）。"""
    if interval not in _INTERVALS:
        raise ValueError(f"interval 仅支持 {'/'.join(sorted(_INTERVALS))}")
    bucket = func.date_trunc(interval, TelemetrySnapshot.recorded_at).label("bucket")
    stmt = (
        select(
            bucket,
            func.avg(TelemetrySnapshot.value).label("value"),
            func.count(TelemetrySnapshot.id).label("count"),
        )
        .where(
            *_ok_conditions(),
            TelemetrySnapshot.equipment_no == equipment_no,
            TelemetrySnapshot.metric == metric,
            TelemetrySnapshot.recorded_at >= from_,
            TelemetrySnapshot.recorded_at <= to,
        )
        .group_by("bucket")
        .order_by("bucket")
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"ts": r.bucket, "value": float(r.value), "count": int(r.count)}
        for r in rows
    ]


async def list_alarms(
    db: AsyncSession,
    *,
    status: str | None = None,
    equipment_no: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TelemetryAlarmRecord], int]:
    """报警记录分页查询（时间倒序）。

    Web 端点 GET /telemetry/alarms 与 business_agent query_telemetry_alarms
    共用（原先内联在 API 层）；date_from/date_to 按报警发生时间 recorded_at
    过滤（date_to 含当日），Web 端点不传即无日期过滤、行为不变。
    """
    if status is not None and status not in _ALARM_STATUSES:
        raise ValueError(f"status 仅支持 {'/'.join(sorted(_ALARM_STATUSES))}")
    stmt = select(TelemetryAlarmRecord).where(TelemetryAlarmRecord.is_deleted.is_(False))
    if status:
        stmt = stmt.where(TelemetryAlarmRecord.status == status)
    if equipment_no:
        stmt = stmt.where(TelemetryAlarmRecord.equipment_no == equipment_no)
    if date_from is not None:
        stmt = stmt.where(TelemetryAlarmRecord.recorded_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(
            TelemetryAlarmRecord.recorded_at < date_to + timedelta(days=1)
        )
    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(TelemetryAlarmRecord.created_at.desc())
            .offset((max(page, 1) - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total
