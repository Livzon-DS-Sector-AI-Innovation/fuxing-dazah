"""facilities-p2 票 01：telemetry API（latest/history）sealed_client 集成测试。

照 test_facility_api 模式：端点内不 commit（本组只读），外层事务回滚清场。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.safety.telemetry.store import upsert_snapshots

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _r(eq: str, metric: str, value: float, ts: datetime, unit: str = "MPa") -> dict:
    return {"equipment_no": eq, "metric": metric, "value": value, "unit": unit, "recorded_at": ts}


async def test_latest_empty(sealed_client):
    ac, _ = sealed_client
    resp = await ac.get("/api/v1/safety/telemetry/latest")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_latest_returns_newest_per_metric(sealed_client):
    ac, session = sealed_client
    await upsert_snapshots(
        session,
        [_r("GL-01", "汽压", 0.8, T0), _r("GL-01", "汽压", 0.9, T0 + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    await session.flush()
    resp = await ac.get("/api/v1/safety/telemetry/latest")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["value"] == 0.9
    # equipment_no 过滤
    resp2 = await ac.get("/api/v1/safety/telemetry/latest?equipment_no=GL-99")
    assert resp2.json()["data"]["items"] == []


async def test_history_bucketing_and_validation(sealed_client):
    ac, session = sealed_client
    await upsert_snapshots(
        session,
        [
            _r("GL-01", "汽压", 0.8, T0),
            _r("GL-01", "汽压", 1.0, T0 + timedelta(minutes=10)),
            _r("GL-01", "汽压", 0.6, T0 + timedelta(hours=1)),
        ],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    await session.flush()
    from_iso = T0.isoformat().replace("+00:00", "Z")
    to_iso = (T0 + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    resp = await ac.get(
        "/api/v1/safety/telemetry/history",
        params={"equipment_no": "GL-01", "metric": "汽压", "interval": "hour",
                "from": from_iso, "to": to_iso},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["interval"] == "hour"
    assert [p["count"] for p in data["points"]] == [2, 1]

    # interval 白名单校验
    bad = await ac.get(
        "/api/v1/safety/telemetry/history",
        params={"equipment_no": "GL-01", "metric": "汽压", "interval": "week"},
    )
    assert bad.status_code == 422

    # from > to 拒绝
    inv = await ac.get(
        "/api/v1/safety/telemetry/history",
        params={"equipment_no": "GL-01", "metric": "汽压",
                "from": to_iso, "to": from_iso},
    )
    assert inv.status_code == 422


async def test_history_default_window_no_params(sealed_client):
    ac, _ = sealed_client
    resp = await ac.get(
        "/api/v1/safety/telemetry/history",
        params={"equipment_no": "GL-01", "metric": "汽压"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["points"] == []


# ── 票 02：rules / alarms ────────────────────────────────────────────


async def test_rules_endpoint_default_and_override(sealed_client, monkeypatch):
    ac, _ = sealed_client
    monkeypatch.setenv("SAFETY_TELEMETRY_RULES", "")
    resp = await ac.get("/api/v1/safety/telemetry/rules")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items and all(i["source"] == "default" for i in items)
    metrics = {i["metric"] for i in items}
    assert {"汽压", "水位", "炉膛温度"} <= metrics

    monkeypatch.setenv(
        "SAFETY_TELEMETRY_RULES", '[{"metric":"汽压","equipment_no":"GL-01","max":1.6}]'
    )
    resp2 = await ac.get("/api/v1/safety/telemetry/rules")
    items2 = resp2.json()["data"]["items"]
    override = [i for i in items2 if i.get("equipment_no") == "GL-01"]
    assert len(override) == 1 and override[0]["max"] == 1.6
    assert override[0]["source"] == "override"


async def test_alarms_list_with_filters(sealed_client):
    from app.modules.safety.models import TelemetryAlarmRecord

    ac, session = sealed_client
    for i, status in enumerate(("firing", "firing", "acked")):
        session.add(
            TelemetryAlarmRecord(
                equipment_no="GL-01", metric="汽压", value=1.2 + i,
                recorded_at=T0 + timedelta(minutes=i),
                rule_desc="汽压超上限", level="warning", status=status,
                dedupe_key=f"k{i}|{i}",
            )
        )
    await session.flush()

    resp = await ac.get("/api/v1/safety/telemetry/alarms")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 3

    resp2 = await ac.get("/api/v1/safety/telemetry/alarms?status=firing")
    assert resp2.json()["data"]["total"] == 2

    resp3 = await ac.get(
        "/api/v1/safety/telemetry/alarms?status=resolved"
    )
    assert resp3.json()["data"]["items"] == []


# ── 票 02：报警群卡内容（mock 通知断言单卡）──────────────────────────


async def test_alarm_notifier_sends_single_card_and_digest(db_session, monkeypatch):
    from app.modules.safety.telemetry.notify import TelemetryAlarmNotifier

    sent: list[tuple[str, str, str]] = []
    digests: list[tuple[str, str]] = []

    async def fake_sender(chat_id, title, content, *args, **kwargs):
        sent.append((chat_id, title, content))
        return "om_x"

    async def fake_digest(report_date, key, cell, **kwargs):
        digests.append((key, cell.stats))
        return True

    notifier = TelemetryAlarmNotifier(
        sender=fake_sender, digest=fake_digest, chat_id="oc_test",
        equipment_info={},
    )
    from app.modules.safety.models import TelemetryAlarmRecord

    alarms = [
        TelemetryAlarmRecord(
            equipment_no="GL-01", metric="汽压", value=1.3,
            recorded_at=T0, rule_desc="汽压 1.3 连续2点超上限 1.0MPa",
            level="warning", status="firing", dedupe_key="a|1",
        ),
        TelemetryAlarmRecord(
            equipment_no="GL-02", metric="水位", value=-60,
            recorded_at=T0, rule_desc="水位 -60 连续2点低于下限 -50mm",
            level="alarm", status="firing", dedupe_key="b|2",
        ),
    ]
    db_session.add_all(alarms)
    await db_session.flush()

    await notifier.on_alarms(db_session, alarms)

    assert len(sent) == 1  # 单卡合并
    chat_id, title, content = sent[0]
    assert chat_id == "oc_test"
    assert "2 条" in title
    assert "GL-01" in content and "GL-02" in content
    assert "超上限" in content and "低于下限" in content
    assert "ou_495039d6335d347b07ff92ad982b3b4e" in content  # @安管
    assert len(digests) == 1 and digests[0][0] == "telemetry_alarm"
    assert "2" in digests[0][1]
