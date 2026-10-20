"""报警处置闭环与待补录人工确认编排（facilities-p2 票 04）。

状态机（与校验任务「不处理完不关闭」同语义）：firing → acked（值班确认）
→ resolved（处置说明必填）。不允许跳过 acked 直接 resolved。

confirm 语义：pending_review 行软删（审计留痕）+ 人工值落 manual 快照
（唯一键 ON CONFLICT 覆写——人工补录胜过机器值），原消息溯源字段保留。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    ALARM_STATUS_ACKED,
    ALARM_STATUS_FIRING,
    ALARM_STATUS_RESOLVED,
    PARSE_METHOD_MANUAL,
    PARSE_STATUS_PENDING_REVIEW,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.telemetry.store import upsert_snapshots


class AlarmStateError(ValueError):
    """非法状态迁移（API 层映射 409）。"""


async def ack_alarm(
    db: AsyncSession, alarm: TelemetryAlarmRecord, *, operator: str
) -> TelemetryAlarmRecord:
    """firing → acked（值班确认留痕）。"""
    if alarm.status != ALARM_STATUS_FIRING:
        raise AlarmStateError("仅 firing 报警可确认（当前 %s）" % alarm.status)
    alarm.status = ALARM_STATUS_ACKED
    alarm.acked_at = datetime.now(UTC)
    alarm.acked_by = operator
    await db.flush()
    return alarm


async def resolve_alarm(
    db: AsyncSession,
    alarm: TelemetryAlarmRecord,
    *,
    note: str,
    operator: str,
) -> TelemetryAlarmRecord:
    """acked → resolved（处置说明必填，结论留痕）。"""
    if alarm.status != ALARM_STATUS_ACKED:
        raise AlarmStateError(
            "须先值班确认（acked）再处置关闭（当前 %s）" % alarm.status
        )
    alarm.status = ALARM_STATUS_RESOLVED
    alarm.resolved_at = datetime.now(UTC)
    alarm.resolution_note = note.strip()
    await db.flush()
    return alarm


async def get_alarm(db: AsyncSession, alarm_id: uuid.UUID) -> TelemetryAlarmRecord | None:
    alarm = await db.get(TelemetryAlarmRecord, alarm_id)
    if alarm is None or alarm.is_deleted:
        return None
    return alarm


async def list_pending_reviews(
    db: AsyncSession, *, page: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """待补录列表（pending_review 且未软删，时间倒序分页）。"""
    from sqlalchemy import func

    base = select(TelemetrySnapshot).where(
        TelemetrySnapshot.is_deleted.is_(False),
        TelemetrySnapshot.parse_status == PARSE_STATUS_PENDING_REVIEW,
    )
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        await db.execute(
            base.order_by(TelemetrySnapshot.recorded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = [_pending_row_out(r) for r in rows]
    return items, total


def _pending_row_out(r: TelemetrySnapshot) -> dict:
    return {
        "id": str(r.id),
        "equipment_no": r.equipment_no,
        "metric": r.metric,
        "value": r.value,
        "unit": r.unit,
        "recorded_at": r.recorded_at,
        "raw_message_id": r.raw_message_id,
        "raw_excerpt": r.raw_excerpt,
        "parse_method": r.parse_method,
        "created_at": r.created_at,
    }


async def confirm_pending_review(
    db: AsyncSession,
    snapshot_id: uuid.UUID,
    *,
    equipment_no: str,
    readings: list[dict[str, Any]],
) -> list[TelemetrySnapshot]:
    """人工补录确认：pending 行软删 + manual 快照覆写落库。

    readings：[{metric, value, unit?, recorded_at?}]（recorded_at 缺省用
    pending 行的原消息时间；原行已抽出的数值仅作表单预填参考，以人工值为准）。
    """
    row = await db.get(TelemetrySnapshot, snapshot_id)
    if row is None or row.is_deleted:
        raise LookupError("待补录记录不存在")
    if row.parse_status != PARSE_STATUS_PENDING_REVIEW:
        raise AlarmStateError("该记录不是待补录状态（%s）" % row.parse_status)

    normalized: list[dict] = []
    for r in readings:
        metric = str(r.get("metric", "") or "").strip()
        if not metric:
            raise ValueError("补录指标（metric）必填")
        try:
            value = float(r.get("value"))
        except (TypeError, ValueError):
            raise ValueError("补录数值（value）必须为数字") from None
        recorded_at = r.get("recorded_at")
        if isinstance(recorded_at, str):
            from app.modules.safety.telemetry.store import coerce_recorded_at

            recorded_at = coerce_recorded_at(recorded_at)
        normalized.append({
            "equipment_no": equipment_no,
            "metric": metric,
            "value": value,
            "unit": r.get("unit"),
            "recorded_at": recorded_at or row.recorded_at,
        })

    # 人工值落 manual 快照（冲突覆写：人工补录胜过机器值），溯源字段保留
    inserted = await upsert_snapshots(
        db,
        normalized,
        parse_method=PARSE_METHOD_MANUAL,
        raw_message_id=row.raw_message_id,
        raw_excerpt=row.raw_excerpt,
        overwrite=True,
    )

    row.is_deleted = True  # 软删 pending 行（审计留痕不物理删）
    await db.flush()
    return inserted
