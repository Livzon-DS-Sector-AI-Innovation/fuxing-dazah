"""消防报警 AI 结果回写（只写 4 个 AI 列，串行 + 间隔由公共底座保证）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import writer as bd_writer
from app.modules.safety.service.fire_alarm import contract

logger = logging.getLogger(__name__)


class FireAlarmRecordLike(Protocol):
    """回写所需的最小记录属性（ORM 对象与 FireAlarmView 都满足）。"""

    feishu_record_id: str | None
    ai_dimension: str | None
    ai_reason_analysis: str | None
    ai_rectification_direction: str | None
    ai_analyzed_at: Any


def _fields_for(record: FireAlarmRecordLike) -> dict[str, Any]:
    """只构造 4 个 AI 列的写请求；空值不写，不覆盖已有值。"""
    fields: dict[str, Any] = {}
    dimension = contract.dimension_to_option(record.ai_dimension)
    if dimension:
        fields[contract.AI_DIMENSION_FIELD] = dimension
    if record.ai_reason_analysis:
        fields[contract.AI_REASON_ANALYSIS_FIELD] = record.ai_reason_analysis
    if record.ai_rectification_direction:
        fields[contract.AI_RECTIFICATION_DIRECTION_FIELD] = (
            record.ai_rectification_direction
        )
    if record.ai_analyzed_at is not None:
        fields[contract.AI_ANALYZED_AT_FIELD] = bd_fields.utc_to_ms(
            record.ai_analyzed_at
        )
    return fields


async def writeback_ai_results(
    records: Sequence[FireAlarmRecordLike],
    *,
    writer: bd_writer.BitableRecordWriter | None = None,
    interval_seconds: float = bd_writer.WRITEBACK_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bd_writer.WritebackResult:
    """把内存中的 AI 分析结果串行回写到 Bitable 4 个 AI 列。

    - 只写 4 个 AI 列，空值不写；
    - 无 feishu_record_id / 无字段可写 -> 跳过；
    - 单条失败不抛出，只计入 failed（下一轮自然补写）。
    """
    target = writer or bd_writer.open_writer("fire_alarm", "alarm")
    pending: list[bd_writer.RecordUpdate] = []
    skipped = 0
    for record in records:
        record_id = str(getattr(record, "feishu_record_id", "") or "")
        fields = _fields_for(record)
        if not record_id or not fields:
            skipped += 1
            continue
        pending.append(bd_writer.RecordUpdate(record_id=record_id, fields=fields))

    result = await bd_writer.write_serial(
        target,
        pending,
        interval_seconds=interval_seconds,
        sleep=sleep,
    )
    result.skipped = skipped
    logger.info(
        "消防 AI 回写完成: attempted=%d written=%d skipped=%d failed=%d",
        result.attempted,
        result.written,
        result.skipped,
        len(result.failed),
    )
    return result


__all__ = ["FireAlarmRecordLike", "writeback_ai_results"]
