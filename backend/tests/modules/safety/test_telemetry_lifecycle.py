"""facilities-p2 票 04：处置闭环状态机 + 人工补录 + 卡片按钮回调。

- 状态机：sealed_client 走 Web API（409 跳步 / resolve 必填 / 留痕字段）；
- 补录：pending 行软删 + manual 覆写 + 趋势可见；
- 卡片：直测 handle_telemetry_card_action 路由（不起 WS）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.safety.models import (
    ALARM_STATUS_ACKED,
    ALARM_STATUS_FIRING,
    PARSE_METHOD_MANUAL,
    PARSE_STATUS_PENDING_REVIEW,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.telemetry.card import handle_telemetry_card_action
from app.modules.safety.telemetry.store import upsert_snapshots

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _alarm(**overrides) -> TelemetryAlarmRecord:
    base = dict(
        equipment_no="GL-01", metric="汽压", value=1.3,
        recorded_at=T0, rule_desc="汽压超上限", level="warning",
        status=ALARM_STATUS_FIRING, dedupe_key=f"k|{uuid.uuid4().hex[:8]}",
    )
    base.update(overrides)
    return TelemetryAlarmRecord(**base)


# ── 状态机（Web API）───────────────────────────────────────────────


async def test_alarm_lifecycle_ack_then_resolve(sealed_client):
    ac, session = sealed_client
    alarm = _alarm()
    session.add(alarm)
    await session.flush()
    aid = str(alarm.id)

    # 跳步：firing 直接 resolve → 409
    bad = await ac.post(f"/api/v1/safety/telemetry/alarms/{aid}/resolve", json={"note": "x"})
    assert bad.status_code == 409

    # ack → acked，留痕
    ok = await ac.post(f"/api/v1/safety/telemetry/alarms/{aid}/ack")
    assert ok.status_code == 200
    data = ok.json()["data"]
    assert data["status"] == "acked" and data["acked_by"] == "admin"
    assert data["acked_at"] is not None

    # 重复 ack → 409
    again = await ac.post(f"/api/v1/safety/telemetry/alarms/{aid}/ack")
    assert again.status_code == 409

    # resolve 缺 note → 422
    empty = await ac.post(f"/api/v1/safety/telemetry/alarms/{aid}/resolve", json={"note": "  "})
    assert empty.status_code == 422

    # resolve → resolved，处置说明留痕
    done = await ac.post(
        f"/api/v1/safety/telemetry/alarms/{aid}/resolve", json={"note": "已泄压并检修安全阀"}
    )
    assert done.status_code == 200
    final = done.json()["data"]
    assert final["status"] == "resolved"
    assert final["resolution_note"] == "已泄压并检修安全阀"
    assert final["resolved_at"] is not None

    # resolved 后再操作 → 409
    post = await ac.post(f"/api/v1/safety/telemetry/alarms/{aid}/ack")
    assert post.status_code == 409


# ── 待补录：列表 + 确认转正 ─────────────────────────────────────────


async def test_pending_review_confirm_flow(sealed_client):
    ac, session = sealed_client
    pending = await upsert_snapshots(
        session,
        [{"equipment_no": None, "metric": "汽压", "value": 0.8, "unit": "MPa",
          "recorded_at": T0}],
        parse_method="ai", parse_status=PARSE_STATUS_PENDING_REVIEW,
        raw_message_id="om_p", raw_excerpt="汽压好像0.8",
    )
    await session.flush()

    # 列表可见
    resp = await ac.get("/api/v1/safety/telemetry/pending-reviews")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["raw_excerpt"] == "汽压好像0.8"
    assert items[0]["metric"] == "汽压" and items[0]["value"] == 0.8  # 预填参考

    # 确认：设备编号必填
    no_eq = await ac.post(
        f"/api/v1/safety/telemetry/pending-reviews/{pending[0].id}/confirm",
        json={"equipment_no": " ", "readings": [{"metric": "汽压", "value": 0.8}]},
    )
    assert no_eq.status_code == 422

    # 确认成功：manual 落库 + pending 软删
    ok = await ac.post(
        f"/api/v1/safety/telemetry/pending-reviews/{pending[0].id}/confirm",
        json={"equipment_no": "GL-01",
              "readings": [{"metric": "汽压", "value": 0.82, "unit": "MPa"}]},
    )
    assert ok.status_code == 200
    data = ok.json()["data"]
    assert data["confirmed"] is True
    assert data["snapshots"][0]["parse_method"] == "manual"
    assert data["snapshots"][0]["value"] == 0.82

    # pending 行软删、manual 行生效（含人工修正值）
    rows = (await session.execute(select(TelemetrySnapshot))).scalars().all()
    live = [r for r in rows if not r.is_deleted]
    deleted = [r for r in rows if r.is_deleted]
    assert len(live) == 1 and live[0].equipment_no == "GL-01"
    assert live[0].value == 0.82 and live[0].parse_method == PARSE_METHOD_MANUAL
    assert len(deleted) == 1 and deleted[0].parse_status == PARSE_STATUS_PENDING_REVIEW
    # 原消息溯源保留
    assert live[0].raw_message_id == "om_p" and "汽压" in (live[0].raw_excerpt or "")

    # 列表清空
    resp2 = await ac.get("/api/v1/safety/telemetry/pending-reviews")
    assert resp2.json()["data"]["items"] == []

    # 再确认同一行 → 404/409（已处理）
    dup = await ac.post(
        f"/api/v1/safety/telemetry/pending-reviews/{pending[0].id}/confirm",
        json={"equipment_no": "GL-01", "readings": [{"metric": "汽压", "value": 0.9}]},
    )
    assert dup.status_code in (404, 409)


async def test_confirm_overwrites_machine_value(sealed_client):
    """同 (设备, 指标, 时间) 已有机器行时，confirm 人工值覆写胜出。"""
    ac, session = sealed_client
    await upsert_snapshots(
        session,
        [{"equipment_no": "GL-02", "metric": "水位", "value": -10, "unit": "mm",
          "recorded_at": T0}],
        parse_method="template", raw_message_id="om_m", raw_excerpt="x",
    )
    pending = await upsert_snapshots(
        session,
        [{"equipment_no": None, "metric": None, "value": None, "unit": None,
          "recorded_at": T0 + timedelta(minutes=1)}],
        parse_method="ai", parse_status=PARSE_STATUS_PENDING_REVIEW,
        raw_message_id="om_p2", raw_excerpt="锅炉读数",
    )
    await session.flush()
    ok = await ac.post(
        f"/api/v1/safety/telemetry/pending-reviews/{pending[0].id}/confirm",
        json={"equipment_no": "GL-02",
              "readings": [{"metric": "水位", "value": -15, "unit": "mm",
                            "recorded_at": T0.isoformat()}]},
    )
    assert ok.status_code == 200
    live = (await session.execute(
        select(TelemetrySnapshot).where(TelemetrySnapshot.is_deleted.is_(False))
    )).scalars().all()
    assert len(live) == 1
    assert live[0].value == -15 and live[0].parse_method == PARSE_METHOD_MANUAL


# ── 卡片按钮回调（直测路由）────────────────────────────────────────


async def test_card_ack_all_acks_firing(db_session, monkeypatch):
    """ack_all：本轮 firing 全确认、已确认跳过、不存在跳过（幂等）。"""
    a1, a2 = _alarm(), _alarm()
    db_session.add_all([a1, a2])
    await db_session.flush()

    # 用回滚 session 替换独立事务；_ack_many 内部会 commit——吞掉 commit
    # 只 flush（否则测试数据真落库污染后续用例）
    import contextlib

    class _NoCommitProxy:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def commit(self):
            await self._inner.flush()

    @contextlib.asynccontextmanager
    async def fake_factory():
        yield _NoCommitProxy(db_session)

    import app.core.database as db_mod
    monkeypatch.setattr(db_mod, "async_session_factory", fake_factory)

    payload = {"scope": "telemetry_alarm", "action": "ack_all",
               "alarm_ids": [str(a1.id), str(a2.id), str(uuid.uuid4())]}
    event = {"operator": {"open_id": "ou_zhiban"}}
    result = await handle_telemetry_card_action(payload, event)
    assert result is not None
    assert result["toast"]["type"] == "success"
    assert a1.status == ALARM_STATUS_ACKED and a2.status == ALARM_STATUS_ACKED
    assert a1.acked_by == "ou_zhiban"

    # 重推（at-least-once）：已确认跳过不报错
    result2 = await handle_telemetry_card_action(payload, event)
    assert result2["toast"]["type"] == "success"


async def test_card_unknown_action_returns_none():
    result = await handle_telemetry_card_action(
        {"scope": "telemetry_alarm", "action": "weird"}, {}
    )
    assert result is None


async def test_card_missing_ids_toast_error():
    result = await handle_telemetry_card_action(
        {"scope": "telemetry_alarm", "action": "ack_all", "alarm_ids": []}, {}
    )
    assert result is not None and result["toast"]["type"] == "error"
