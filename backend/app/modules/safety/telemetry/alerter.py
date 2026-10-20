"""报警编排：新增快照 → 规则判定 → 落库（静默窗去重）→ 通知（facilities-p2 票 02）。

「当轮即判即发」（DESIGN §5.2）：只对**本轮新插入**的快照判定（重放零新增
不重判）；同 (设备, 指标) 分组一次取尾部历史，以组内最新点为判定点。
静默窗口=dedupe_key 时间桶唯一键（冲突即窗内同源，静默跳过）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    ALARM_STATUS_FIRING,
    PARSE_STATUS_OK,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.facilities.engine import category_label
from app.modules.safety.telemetry.rules import (
    RuleSpec,
    dedupe_key,
    evaluate,
    rule_for,
)

logger = logging.getLogger(__name__)

# 默认静默窗口（秒）：同源报警 30 分钟内不重发（DESIGN §5.2 / P6 拍板）
DEFAULT_SILENCE_SECONDS = 1800


class AlarmNotifier(Protocol):
    """报警通知出口（真实=群卡+速递格子，见 notify.py；测试=断言替身）。"""

    async def on_alarms(
        self, session: AsyncSession, alarms: list[TelemetryAlarmRecord]
    ) -> None: ...


def _silence_seconds() -> int:
    from app.modules.safety.app_config.store import store

    return store.get_int(
        "SAFETY_TELEMETRY_SILENCE_SECONDS", DEFAULT_SILENCE_SECONDS, minimum=60
    )


def effective_silence_seconds(store_values: dict[str, int] | None = None) -> int:
    """测试可注入的静默窗口读取（默认走 app_config）。"""
    if store_values is not None:
        return store_values.get("silence", DEFAULT_SILENCE_SECONDS)
    return _silence_seconds()


async def _tail_history(
    db: AsyncSession, equipment_no: str, metric: str, limit: int
) -> list[tuple[datetime, float]]:
    """该设备指标的尾部点位（升序；有效行口径与读数卡同源，防两处漂移）。"""
    from app.modules.safety.telemetry.query import _ok_conditions

    rows = (
        await db.execute(
            select(TelemetrySnapshot.recorded_at, TelemetrySnapshot.value)
            .where(
                *_ok_conditions(),
                TelemetrySnapshot.equipment_no == equipment_no,
                TelemetrySnapshot.metric == metric,
            )
            .order_by(TelemetrySnapshot.recorded_at.desc())
            .limit(limit)
        )
    ).all()
    return [(r.recorded_at, r.value) for r in reversed(rows)]


async def evaluate_and_alarm(
    db: AsyncSession,
    new_snapshots: list[TelemetrySnapshot],
    *,
    rules: tuple[RuleSpec, ...],
    now: datetime,
    notifier: AlarmNotifier | None = None,
    equipment_info: dict[str, dict[str, Any]] | None = None,
    silence_seconds: int | None = None,
) -> list[TelemetryAlarmRecord]:
    """对新增快照跑判定，命中即落 firing 报警（静默窗去重），返回新报警。

    equipment_info：设备编号 → {"category": …, "department": …}（台账/调用方
    提供；缺省按通配规则匹配）。通知出口失败不抛（fail-open，报警落库优先）。
    """
    info = equipment_info or {}
    silence = silence_seconds if silence_seconds is not None else _silence_seconds()

    # 同 (设备, 指标) 分组：一组一次历史查询、一次判定（判定点=组内最新）
    groups: dict[tuple[str, str], TelemetrySnapshot] = {}
    for snap in new_snapshots:
        if not snap.equipment_no or not snap.metric or snap.value is None:
            continue
        key = (snap.equipment_no, snap.metric)
        current = groups.get(key)
        if current is None or (snap.recorded_at, snap.id) > (current.recorded_at, current.id):
            groups[key] = snap

    created: list[TelemetryAlarmRecord] = []
    for (equipment_no, metric), snap in groups.items():
        meta = info.get(equipment_no) or {}
        # 类别归一（「立式锅炉」→「锅炉」）后匹配类别级规则，与校验任务分组同口径
        rule = rule_for(rules, equipment_no, category_label(meta.get("category")), metric)
        if rule is None:
            continue
        history = await _tail_history(db, equipment_no, metric, rule.consecutive + 1)
        violation = evaluate(history, rule, now=now)
        if violation is None:
            continue

        key = dedupe_key(equipment_no, metric, violation.level, now, silence)
        stmt = (
            insert(TelemetryAlarmRecord)
            .values(
                equipment_no=equipment_no,
                metric=metric,
                value=violation.value,
                recorded_at=violation.recorded_at,
                rule_desc=violation.rule_desc,
                level=violation.level,
                status=ALARM_STATUS_FIRING,
                dedupe_key=key,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(TelemetryAlarmRecord)
        )
        row = (await db.execute(stmt)).scalars().first()
        if row is not None:
            created.append(row)
    await db.flush()

    if created and notifier is not None:
        try:
            await notifier.on_alarms(db, created)
        except Exception:
            logger.warning(
                "遥测报警通知发送失败（报警已落库，不影响主链路）", exc_info=True
            )
    return created
