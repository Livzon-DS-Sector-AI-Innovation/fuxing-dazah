"""facilities-p2 票 05：§9 验收剧本后半段端到端（集成一条链）。

群发超限抄表消息 → 采集解析落快照 → 当轮规则命中报警（mock 通知断言单卡）
→ 静默窗内同源不重复 → 值班 ack → 处置 resolve（留痕）→ 趋势序列可见。
接缝：FakeAdapter + 假 AI + db_session 回滚 + 断言通知器。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.safety.models import (
    ALARM_STATUS_ACKED,
    ALARM_STATUS_RESOLVED,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.telemetry.alerter import evaluate_and_alarm
from app.modules.safety.telemetry.collector import run_collect_round
from app.modules.safety.telemetry.lifecycle import ack_alarm, resolve_alarm
from app.modules.safety.telemetry.query import history_series, latest_values
from app.modules.safety.telemetry.rules import DEFAULT_RULES
from app.modules.safety.telemetry.source import SourceMessage

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
EQUIPMENT = {"GL-01": {"category": "锅炉", "department": "动力部"}}


class FakeAdapter:
    def __init__(self, messages: list[SourceMessage]) -> None:
        self.messages = messages

    async def fetch_new_messages(self) -> list[SourceMessage]:
        return list(self.messages)


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[list[TelemetryAlarmRecord]] = []

    async def on_alarms(self, session, alarms) -> None:
        self.calls.append(list(alarms))


async def _ai_chat(message: SourceMessage, allowed: set[str]) -> dict:
    return {"type": "chat"}


def _msg(mid: str, text: str, minutes: int) -> SourceMessage:
    return SourceMessage(
        message_id=mid, sender_id="ou_worker", sender_name="抄表员",
        msg_type="text", text=text, image_key=None,
        create_time=T0 + timedelta(minutes=minutes),
    )


async def test_e2e_overlimit_message_to_alarm_to_trend(db_session):
    notifier = RecordingNotifier()

    # ① 群发两条超限抄表消息（锅炉连续两班报汽压 1.2/1.3，超上限 1.0）
    adapter = FakeAdapter([
        _msg("om_e1", "GL-01 汽压 1.2MPa", minutes=0),
        _msg("om_e2", "GL-01 汽压 1.3MPa", minutes=5),
    ])
    r1 = await run_collect_round(
        db_session, adapter=adapter, ai_parser=_ai_chat,
        sender_map={}, rules=DEFAULT_RULES, equipment_info=EQUIPMENT,
        notifier=notifier, chat_id="oc_boiler", now=T0 + timedelta(minutes=6),
    )
    assert r1.inserted == 2 and r1.alarms == 1  # 当轮即判即发

    # ② 群卡通知收到单卡（一条报警）
    assert len(notifier.calls) == 1
    alarm = notifier.calls[0][0]
    assert alarm.equipment_no == "GL-01" and "超上限" in alarm.rule_desc
    assert alarm.status == "firing"

    # ③ 静默窗内同源再超限（第三班 1.4）→ 不重复报警
    adapter2 = FakeAdapter([_msg("om_e3", "GL-01 汽压 1.4MPa", minutes=10)])
    r2 = await run_collect_round(
        db_session, adapter=adapter2, ai_parser=_ai_chat,
        sender_map={}, rules=DEFAULT_RULES, equipment_info=EQUIPMENT,
        notifier=notifier, chat_id="oc_boiler", now=T0 + timedelta(minutes=11),
    )
    assert r2.alarms == 0 and len(notifier.calls) == 1
    rows = (await db_session.execute(select(TelemetryAlarmRecord))).scalars().all()
    assert len(rows) == 1

    # ④ 值班 ack → 处置 resolve（结论留痕）
    await ack_alarm(db_session, alarm, operator="ou_zhiban")
    assert alarm.status == ALARM_STATUS_ACKED and alarm.acked_by == "ou_zhiban"
    await resolve_alarm(db_session, alarm, note="已泄压并联系检修校验安全阀", operator="ou_charger")
    assert alarm.status == ALARM_STATUS_RESOLVED
    assert alarm.resolution_note == "已泄压并联系检修校验安全阀"

    # ⑤ 趋势与实时读数可见（三点序列 + 最新值）
    series = await history_series(
        db_session, "GL-01", "汽压",
        from_=T0 - timedelta(hours=1), to=T0 + timedelta(hours=1), interval="hour",
    )
    assert len(series) == 1 and series[0]["count"] == 3
    assert series[0]["value"] == (1.2 + 1.3 + 1.4) / 3
    latest = await latest_values(db_session, equipment_no="GL-01")
    assert latest[0]["value"] == 1.4 and latest[0]["metric"] == "汽压"


async def test_e2e_pending_review_manual_confirm_to_trend(db_session):
    """双败消息→pending→人工补录→快照/趋势可见（§9 剧本待补录分支）。"""
    from app.modules.safety.telemetry.lifecycle import confirm_pending_review

    async def ai_broken(message: SourceMessage, allowed: set[str]) -> dict:
        raise RuntimeError("ai down")

    adapter = FakeAdapter([_msg("om_bad", "锅炉今天不太对劲", minutes=0)])
    r = await run_collect_round(
        db_session, adapter=adapter, ai_parser=ai_broken,
        sender_map={}, rules=DEFAULT_RULES, equipment_info=EQUIPMENT,
        notifier=None, chat_id="oc_boiler", now=T0 + timedelta(minutes=5),
    )
    assert r.pending == 1
    pending = (
        await db_session.execute(select(TelemetrySnapshot))
    ).scalars().first()
    assert pending.parse_status == "pending_review"

    final = await confirm_pending_review(
        db_session, pending.id, equipment_no="GL-01",
        readings=[{"metric": "汽压", "value": 0.7, "unit": "MPa"}],
    )
    assert final[0].parse_method == "manual" and final[0].value == 0.7

    latest = await latest_values(db_session)
    assert latest[0]["equipment_no"] == "GL-01" and latest[0]["value"] == 0.7
    remaining_pending = [
        s for s in (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
        if s.parse_status == "pending_review" and not s.is_deleted
    ]
    assert remaining_pending == []


async def test_e2e_no_source_three_state_fallback(db_session):
    """锅炉群未配置：采集 no_source、零 IO、页面层空数据兜底。"""
    adapter = FakeAdapter([_msg("om_x", "GL-01 汽压 0.8MPa", minutes=0)])
    r = await run_collect_round(
        db_session, adapter=adapter, ai_parser=_ai_chat,
        sender_map={}, rules=DEFAULT_RULES, equipment_info=EQUIPMENT,
        chat_id="", now=T0,
    )
    assert r.no_source is True and r.fetched == 0
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert rows == []
    latest = await latest_values(db_session)
    assert latest == []  # 前端 latest 空态 → 引导文案兜底
