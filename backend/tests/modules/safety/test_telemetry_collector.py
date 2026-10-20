"""facilities-p2 票 03：锅炉群消息采集 worker。

接缝：FakeSourceAdapter（消息序列替身）+ 假 AI 解析函数 + db_session 回滚 +
断言通知器。覆盖：模板命中幂等 / AI 兜底 / 双败 pending / 闲聊跳过 / 发送人
映射归属 / no_source / 游标重启安全 / 新快照接线报警链。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.modules.safety.models import (
    PARSE_STATUS_PENDING_REVIEW,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.telemetry.collector import run_collect_round
from app.modules.safety.telemetry.rules import DEFAULT_RULES
from app.modules.safety.telemetry.source import SourceMessage

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


class FakeAdapter:
    """消息序列替身：每次 fetch 返回全量（模拟拉群历史），幂等由游标+DB 防重。"""

    def __init__(self, messages: list[SourceMessage]) -> None:
        self.messages = messages
        self.fetch_calls = 0

    async def fetch_new_messages(self) -> list[SourceMessage]:
        self.fetch_calls += 1
        return list(self.messages)


def _msg(
    mid: str,
    text: str,
    *,
    sender: str = "ou_worker",
    minutes: int = 0,
    msg_type: str = "text",
    image_key: str | None = None,
) -> SourceMessage:
    return SourceMessage(
        message_id=mid,
        sender_id=sender,
        sender_name="抄表员",
        msg_type=msg_type,
        text=text,
        image_key=image_key,
        create_time=T0 + timedelta(minutes=minutes),
    )


async def _fake_ai_ok(message: SourceMessage, allowed: set[str]) -> dict:
    """假 AI：返回两条读数（含设备编号）。"""
    return {
        "type": "readings",
        "readings": [
            {"equipment_no": "GL-01", "metric": "汽压", "value": 0.75, "unit": "MPa"},
            {"equipment_no": "GL-01", "metric": "水位", "value": -20, "unit": "mm"},
        ],
    }


async def _fake_ai_chat(message: SourceMessage, allowed: set[str]) -> dict:
    return {"type": "chat"}


class FlakyAI:
    """假 AI：始终抛错（模拟 AI 链路不可用）。"""

    async def __call__(self, message: SourceMessage, allowed: set[str]) -> dict:
        raise RuntimeError("ai down")


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    async def on_alarms(self, session, alarms) -> None:
        self.calls.append(list(alarms))


EQUIPMENT = {"GL-01": {"category": "锅炉", "department": "动力部"}}


async def _round(db, adapter, *, ai=None, sender_map=None, notifier=None, now=None):
    return await run_collect_round(
        db,
        adapter=adapter,
        ai_parser=ai or _fake_ai_ok,
        sender_map=sender_map or {},
        rules=DEFAULT_RULES,
        equipment_info=EQUIPMENT,
        notifier=notifier,
        chat_id="oc_test",
        now=now or T0 + timedelta(minutes=10),
    )


# ── 模板命中：解析落快照 + 幂等 ────────────────────────────────────


async def test_template_hit_inserts_snapshots_idempotent(db_session):
    adapter = FakeAdapter([
        _msg("om_1", "GL-01 汽压 0.8MPa\n水位 -30mm", minutes=0),
    ])
    r1 = await _round(db_session, adapter, ai=_fake_ai_chat)
    assert r1.inserted == 2
    assert r1.pending == 0 and r1.skipped == 0
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert len(rows) == 2
    assert all(r.parse_method == "template" for r in rows)
    by_metric = {r.metric: r for r in rows}
    assert by_metric["汽压"].value == 0.8 and by_metric["汽压"].equipment_no == "GL-01"
    assert by_metric["水位"].value == -30 and by_metric["水位"].unit == "mm"


async def test_replayed_messages_not_duplicated(db_session):
    """重拉同批消息（游标推进后模拟重启回退/重推）→ 零新增。"""
    adapter = FakeAdapter([
        _msg("om_1", "GL-01 汽压 0.8MPa\n水位 -30mm"),
        _msg("om_2", "GL-01 汽压 0.9MPa", minutes=5),
    ])
    await _round(db_session, adapter, ai=_fake_ai_chat)
    r2 = await _round(db_session, adapter, ai=_fake_ai_chat)
    assert r2.inserted == 0
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert len(rows) == 3


# ── 模板未中走 AI ──────────────────────────────────────────────────


async def test_template_miss_falls_back_to_ai(db_session):
    adapter = FakeAdapter([_msg("om_ai", "锅炉房巡检：GL-01 目前汽压0.75，水位-20，一切正常")])
    r = await _round(db_session, adapter, ai=_fake_ai_ok)
    assert r.inserted == 2
    assert all(r.parse_method == "ai" for r in r.new_snapshots)


async def test_ai_rejects_unknown_metric(db_session):
    """AI 产出不在受控指标集 → 不采信 → pending_review。"""
    async def ai_unknown(message, allowed):
        return {"type": "readings", "readings": [
            {"equipment_no": "GL-01", "metric": "玄学指标", "value": 1.0},
        ]}
    adapter = FakeAdapter([_msg("om_x", "看不懂的抄表")])
    r = await _round(db_session, adapter, ai=ai_unknown)
    assert r.inserted == 0 and r.pending == 1


# ── 双败 pending_review / 闲聊跳过 ─────────────────────────────────


async def test_both_fail_goes_pending_review(db_session):
    adapter = FakeAdapter([_msg("om_p", "锅炉今天声音有点怪，GL-01")])
    r = await _round(db_session, adapter, ai=FlakyAI())
    assert r.pending == 1 and r.inserted == 0
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].parse_status == PARSE_STATUS_PENDING_REVIEW
    assert rows[0].raw_message_id == "om_p"
    assert "声音" in rows[0].raw_excerpt


async def test_chat_message_skipped_not_failure(db_session):
    adapter = FakeAdapter([_msg("om_c", "早上好")])
    r = await _round(db_session, adapter, ai=_fake_ai_chat)
    assert r.skipped == 1 and r.pending == 0 and r.inserted == 0
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert rows == []


# ── 归属：发送人映射兜底 ───────────────────────────────────────────


async def test_sender_map_fills_equipment(db_session, monkeypatch):
    monkeypatch.setenv("SAFETY_TELEMETRY_SENDER_MAP", '{"ou_worker":"GL-01"}')
    adapter = FakeAdapter([_msg("om_s", "汽压 0.8MPa\n水位 -30mm", sender="ou_worker")])
    r = await _round(db_session, adapter, ai=_fake_ai_chat, sender_map={"ou_worker": "GL-01"})
    assert r.inserted == 2
    assert all(s.equipment_no == "GL-01" for s in r.new_snapshots)


async def test_no_equipment_resolved_goes_pending(db_session):
    """无编号无映射 → 数值也不落（归属缺失整条 pending）。"""
    adapter = FakeAdapter([_msg("om_n", "汽压 0.8MPa")])
    r = await _round(db_session, adapter, ai=_fake_ai_chat)
    assert r.pending == 1


# ── no_source：源群未配置 ──────────────────────────────────────────


async def test_no_source_when_chat_unconfigured(db_session, monkeypatch):
    from app.modules.safety.telemetry.collector import source_chat_id

    monkeypatch.setenv("SAFETY_TELEMETRY_SOURCE_CHAT_ID", "")
    assert source_chat_id() == ""
    adapter = FakeAdapter([_msg("om_1", "GL-01 汽压 0.8MPa")])
    r = await run_collect_round(
        db_session, adapter=adapter, ai_parser=_fake_ai_chat,
        sender_map={}, rules=DEFAULT_RULES, equipment_info=EQUIPMENT,
        chat_id="", now=T0,
    )
    assert r.no_source is True
    assert r.inserted == 0 and adapter.fetch_calls == 0


# ── 新快照接线报警链 ──────────────────────────────────────────────


async def test_collect_round_triggers_alarm_on_threshold(db_session):
    notifier = RecordingNotifier()
    adapter = FakeAdapter([
        _msg("om_a", "GL-01 汽压 1.2MPa", minutes=0),
        _msg("om_b", "GL-01 汽压 1.3MPa", minutes=5),
    ])
    r = await _round(db_session, adapter, ai=_fake_ai_chat, notifier=notifier)
    assert r.alarms == 1
    rows = (await db_session.execute(select(TelemetryAlarmRecord))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "firing"
    assert len(notifier.calls) == 1


async def test_round_summary_string(db_session):
    adapter = FakeAdapter([_msg("om_1", "GL-01 汽压 0.8MPa")])
    r = await _round(db_session, adapter, ai=_fake_ai_chat)
    text = r.summary()
    assert "inserted=1" in text


async def test_ai_equipment_not_in_monitored_set_rejected(db_session):
    """AI 读数设备不在 monitored 集（equipment_info keys）→ 拒收进 pending。"""
    async def ai_unknown_eq(message, allowed):
        return {"type": "readings", "readings": [
            {"equipment_no": "XX-99", "metric": "汽压", "value": 0.7},
        ]}
    adapter = FakeAdapter([_msg("om_eq", "某锅炉读数如下")])
    r = await _round(db_session, adapter, ai=ai_unknown_eq)
    assert r.inserted == 0 and r.pending == 1
