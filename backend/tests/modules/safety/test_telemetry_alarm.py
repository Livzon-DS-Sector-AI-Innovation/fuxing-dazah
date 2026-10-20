"""facilities-p2 票 02：报警编排（判定→落库→静默→通知）。

接缝：db_session 回滚事务 + 断言型假通知器（捕获单卡内容与 @ 列表），
照 test_facility_notify 模式。静默窗口=dedupe_key 时间桶唯一键。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.safety.models import TelemetryAlarmRecord
from app.modules.safety.telemetry.alerter import evaluate_and_alarm
from app.modules.safety.telemetry.rules import DEFAULT_RULES
from app.modules.safety.telemetry.store import upsert_snapshots

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


class RecordingNotifier:
    """断言型通知替身：捕获报警批次（单卡内容原料）。"""

    def __init__(self) -> None:
        self.calls: list[list[TelemetryAlarmRecord]] = []

    async def on_alarms(self, session, alarms) -> None:
        self.calls.append(list(alarms))


def _r(eq: str, metric: str, value: float, ts: datetime, unit: str = "MPa") -> dict:
    return {"equipment_no": eq, "metric": metric, "value": value, "unit": unit, "recorded_at": ts}


async def _seed_two_high_points(db, eq="GL-01", base=T0):
    """两连点超上限（默认规则 consecutive=2）→ 必命中。"""
    return await upsert_snapshots(
        db,
        [_r(eq, "汽压", 1.2, base), _r(eq, "汽压", 1.3, base + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_hi", raw_excerpt="汽压 1.2",
    )


async def test_alarm_created_on_new_snapshots_with_streak(db_session):
    notifier = RecordingNotifier()
    new = await _seed_two_high_points(db_session)
    alarms = await evaluate_and_alarm(
        db_session, new, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "立式锅炉"}},
    )
    assert len(alarms) == 1
    a = alarms[0]
    assert a.equipment_no == "GL-01" and a.metric == "汽压"
    assert a.status == "firing" and a.level in ("warning", "alarm")
    assert a.value == 1.3
    assert "超上限" in a.rule_desc
    # 通知收到同一批
    assert len(notifier.calls) == 1 and notifier.calls[0][0].id == a.id


async def test_no_alarm_for_single_spike(db_session):
    """单点毛刺（无连续）不触发上下限报警、不通知。

    用无 rate 的规则隔离测「上下限去抖」语义（默认规则另有变化率维度，
    单点跳变会被 rate 抓住——那是设计内，见 test_telemetry_rules）。
    """
    from app.modules.safety.telemetry.rules import RuleSpec

    notifier = RecordingNotifier()
    new = await upsert_snapshots(
        db_session,
        [_r("GL-01", "汽压", 0.8, T0), _r("GL-01", "汽压", 1.2, T0 + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    alarms = await evaluate_and_alarm(
        db_session, new,
        rules=(RuleSpec(metric="汽压", category="锅炉", min=0.2, max=1.0),),
        now=T0 + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    assert alarms == []
    assert notifier.calls == []


async def test_silence_window_suppresses_same_source(db_session):
    """同源异常 30 分钟内重触发→dedupe_key 唯一键拦下，不新增不通知。"""
    notifier = RecordingNotifier()
    first = await _seed_two_high_points(db_session)
    base = await evaluate_and_alarm(
        db_session, first, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    assert len(base) == 1  # 窗内首报

    # 静默窗内再来两连点（新消息新时间戳，判定仍命中）
    more = await upsert_snapshots(
        db_session,
        [_r("GL-01", "汽压", 1.4, T0 + timedelta(minutes=10)),
         _r("GL-01", "汽压", 1.5, T0 + timedelta(minutes=15))],
        parse_method="template", raw_message_id="om_2", raw_excerpt="x",
    )
    suppressed = await evaluate_and_alarm(
        db_session, more, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=16),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    assert suppressed == []  # 静默窗内同源不重发
    rows = (await db_session.execute(select(TelemetryAlarmRecord))).scalars().all()
    assert len(rows) == 1
    assert len(notifier.calls) == 1


async def test_cross_window_allows_new_alarm(db_session):
    """跨静默窗（>30 分钟）同源再触发→新报警放行。"""
    notifier = RecordingNotifier()
    first = await _seed_two_high_points(db_session)
    await evaluate_and_alarm(
        db_session, first, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    later_base = T0 + timedelta(minutes=40)
    later = await upsert_snapshots(
        db_session,
        [_r("GL-01", "汽压", 1.5, later_base), _r("GL-01", "汽压", 1.6, later_base + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_4", raw_excerpt="x",
    )
    alarms = await evaluate_and_alarm(
        db_session, later, rules=DEFAULT_RULES, now=later_base + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "立式锅炉"}},
    )
    assert len(alarms) == 1
    rows = (await db_session.execute(select(TelemetryAlarmRecord))).scalars().all()
    assert len(rows) == 2
    assert len(notifier.calls) == 2


async def test_replayed_snapshot_not_rejudged(db_session):
    """重放（upsert 零新增）不重判不重报。"""
    notifier = RecordingNotifier()
    new = await _seed_two_high_points(db_session)
    await evaluate_and_alarm(
        db_session, new, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=6),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    replayed = await upsert_snapshots(  # 同 (eq, metric, ts) → 冲突零新增
        db_session,
        [_r("GL-01", "汽压", 1.2, T0), _r("GL-01", "汽压", 1.3, T0 + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_hi", raw_excerpt="x",
    )
    assert replayed == []
    alarms = await evaluate_and_alarm(
        db_session, replayed, rules=DEFAULT_RULES, now=T0 + timedelta(minutes=50),
        notifier=notifier, equipment_info={"GL-01": {"category": "锅炉"}},
    )
    assert alarms == []
    assert len(notifier.calls) == 1  # 仅首轮
