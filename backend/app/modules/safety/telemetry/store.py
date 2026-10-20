"""快照幂等写入（facilities-p2 票 01）。

唯一 (equipment_no, metric, recorded_at) → ON CONFLICT DO NOTHING +
RETURNING 拿「本轮真正新插入」的行（判定报警只看新增，重放不重判）。
pending_review 行 metric/value 可空——PG 唯一索引对 NULL 不去重，待补录行
天然走非幂等路径，由 raw_message_id 查重在采集层防重。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    PARSE_METHOD_TEMPLATE,
    PARSE_STATUS_OK,
    TelemetrySnapshot,
)


async def upsert_snapshots(
    db: AsyncSession,
    readings: list[dict[str, Any]],
    *,
    parse_method: str = PARSE_METHOD_TEMPLATE,
    parse_status: str = PARSE_STATUS_OK,
    raw_message_id: str | None = None,
    raw_excerpt: str | None = None,
    overwrite: bool = False,
) -> list[TelemetrySnapshot]:
    """落一批读数为快照，返回**新插入**的行（冲突行静默跳过）。

    readings 元素：equipment_no / metric / value / unit / recorded_at
    （前两项与 value 允许 None——pending_review 待补录行）。
    overwrite=True：冲突行覆写为本次值（人工补录 confirm 语义——人工值
    胜过机器值，DO UPDATE + RETURNING 返回全部行）。
    """
    inserted: list[TelemetrySnapshot] = []
    for r in readings:
        stmt = (
            insert(TelemetrySnapshot)
            .values(
                equipment_no=r.get("equipment_no"),
                metric=r.get("metric"),
                value=r.get("value"),
                unit=r.get("unit"),
                recorded_at=r["recorded_at"],
                raw_message_id=raw_message_id,
                parse_method=parse_method,
                raw_excerpt=raw_excerpt,
                parse_status=parse_status,
            )
            .returning(TelemetrySnapshot)
        )
        if overwrite:
            stmt = stmt.on_conflict_do_update(
                index_elements=["equipment_no", "metric", "recorded_at"],
                set_={
                    "value": r.get("value"),
                    "unit": r.get("unit"),
                    "parse_method": parse_method,
                    "parse_status": parse_status,
                    "raw_message_id": raw_message_id,
                    "raw_excerpt": raw_excerpt,
                },
            )
        else:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["equipment_no", "metric", "recorded_at"]
            )
        row = (await db.execute(stmt)).scalars().first()
        if row is not None:
            inserted.append(row)
    await db.flush()
    return inserted


async def message_processed(
    db: AsyncSession, raw_message_id: str
) -> bool:
    """该群消息是否已落过任何快照行（at-least-once 重拉防重）。"""
    from sqlalchemy import select

    row = await db.scalar(
        select(TelemetrySnapshot.id)
        .where(TelemetrySnapshot.raw_message_id == raw_message_id)
        .limit(1)
    )
    return row is not None


def excerpt_of(text: str | None, limit: int = 200) -> str | None:
    """原消息摘录（截断留省略号；None 透传）。"""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def coerce_recorded_at(value: Any) -> datetime | None:
    """读数时间归一（datetime 直取；ISO 字符串解析；其余 None）。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
