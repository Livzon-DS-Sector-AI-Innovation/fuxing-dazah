"""facilities-p2 票 01：telemetry 快照基座（ORM/幂等 upsert/latest/history）。

接缝：db_session 回滚事务直测 store 层（照 test_facility_dispatch 模式）；
快照唯一键幂等是采集链防重的地基，必须先行钉死。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.safety.models import TelemetrySnapshot
from app.modules.safety.telemetry.store import upsert_snapshots
from app.modules.safety.telemetry.query import history_series, latest_values

T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _reading(
    eq: str, metric: str, value: float, ts: datetime, *, unit: str = "MPa"
) -> dict:
    return {"equipment_no": eq, "metric": metric, "value": value, "unit": unit, "recorded_at": ts}


# ── upsert 幂等 ─────────────────────────────────────────────────────


async def test_upsert_snapshots_inserts_and_returns_new_rows(db_session):
    new = await upsert_snapshots(
        db_session,
        [_reading("GL-01", "汽压", 0.8, T0), _reading("GL-01", "水位", -30, T0, unit="mm")],
        parse_method="template",
        raw_message_id="om_1",
        raw_excerpt="汽压 0.8\n水位 -30",
    )
    assert len(new) == 2
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert len(rows) == 2
    assert all(r.parse_status == "ok" for r in rows)
    assert {r.raw_message_id for r in rows} == {"om_1"}


async def test_upsert_snapshots_idempotent_on_replay(db_session):
    batch = [_reading("GL-01", "汽压", 0.8, T0)]
    first = await upsert_snapshots(
        db_session, batch, parse_method="template", raw_message_id="om_1", raw_excerpt="汽压 0.8"
    )
    second = await upsert_snapshots(
        db_session, batch, parse_method="template", raw_message_id="om_1", raw_excerpt="汽压 0.8"
    )
    assert len(first) == 1
    assert second == []  # 唯一键拦下，重放零新增
    rows = (await db_session.execute(select(TelemetrySnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == 0.8


async def test_upsert_pending_review_row_without_metric(db_session):
    """解析失败行：metric/value 可空，不受唯一键去重（NULL 不相等）。"""
    row = await upsert_snapshots(
        db_session,
        [{"equipment_no": None, "metric": None, "value": None, "unit": None, "recorded_at": T0}],
        parse_method="template",
        raw_message_id="om_9",
        raw_excerpt="今天锅炉好像不太对",
        parse_status="pending_review",
    )
    assert len(row) == 1
    assert row[0].parse_status == "pending_review"
    assert row[0].metric is None


async def test_upsert_replay_after_partial_conflict_inserts_rest(db_session):
    """同批部分冲突部分新：新行照常落库。"""
    await upsert_snapshots(
        db_session, [_reading("GL-01", "汽压", 0.8, T0)],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    new = await upsert_snapshots(
        db_session,
        [_reading("GL-01", "汽压", 0.8, T0), _reading("GL-01", "汽压", 0.9, T0 + timedelta(minutes=5))],
        parse_method="template", raw_message_id="om_2", raw_excerpt="x",
    )
    assert [r.value for r in new] == [0.9]


# ── latest 聚合 ─────────────────────────────────────────────────────


async def test_latest_values_per_equipment_metric(db_session):
    await upsert_snapshots(
        db_session,
        [
            _reading("GL-01", "汽压", 0.8, T0),
            _reading("GL-01", "汽压", 0.9, T0 + timedelta(minutes=5)),
            _reading("GL-01", "水位", -30, T0 + timedelta(minutes=5), unit="mm"),
            _reading("GL-02", "汽压", 0.7, T0 + timedelta(minutes=10)),
        ],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    items = await latest_values(db_session)
    assert {(i["equipment_no"], i["metric"], i["value"]) for i in items} == {
        ("GL-01", "汽压", 0.9),
        ("GL-01", "水位", -30),
        ("GL-02", "汽压", 0.7),
    }


async def test_latest_values_filters_pending_and_empty_equipment(db_session):
    """pending_review/空设备行不进读数卡；equipment_no 过滤生效。"""
    await upsert_snapshots(
        db_session,
        [_reading("GL-01", "汽压", 0.8, T0), _reading("GL-02", "汽压", 0.7, T0)],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    await upsert_snapshots(
        db_session,
        [{"equipment_no": None, "metric": None, "value": None, "unit": None, "recorded_at": T0}],
        parse_method="template", raw_message_id="om_9", raw_excerpt="x",
        parse_status="pending_review",
    )
    items = await latest_values(db_session, equipment_no="GL-01")
    assert [(i["equipment_no"], i["metric"]) for i in items] == [("GL-01", "汽压")]


# ── history 序列 ────────────────────────────────────────────────────


async def test_history_series_hourly_buckets(db_session):
    points = [
        _reading("GL-01", "汽压", 0.8, T0),
        _reading("GL-01", "汽压", 0.9, T0 + timedelta(minutes=10)),
        _reading("GL-01", "汽压", 1.1, T0 + timedelta(hours=1, minutes=5)),
    ]
    await upsert_snapshots(
        db_session, points, parse_method="template", raw_message_id="om_1", raw_excerpt="x"
    )
    series = await history_series(
        db_session, "GL-01", "汽压",
        from_=T0 - timedelta(hours=1), to=T0 + timedelta(hours=2), interval="hour",
    )
    assert len(series) == 2
    assert series[0]["value"] == pytest.approx((0.8 + 0.9) / 2)
    assert series[0]["count"] == 2
    assert series[1]["value"] == pytest.approx(1.1)


async def test_history_series_daily_buckets_and_range(db_session):
    day1 = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
    day2 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    await upsert_snapshots(
        db_session,
        [
            _reading("GL-01", "汽压", 0.8, day1),
            _reading("GL-01", "汽压", 1.0, day1 + timedelta(hours=4)),
            _reading("GL-01", "汽压", 0.6, day2),
        ],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    series = await history_series(
        db_session, "GL-01", "汽压",
        from_=day1, to=day2 + timedelta(hours=23), interval="day",
    )
    assert [s["count"] for s in series] == [2, 1]
    assert series[0]["value"] == pytest.approx(0.9)
    # 范围过滤：只看 day2
    only2 = await history_series(
        db_session, "GL-01", "汽压", from_=day2, to=day2 + timedelta(hours=23), interval="day"
    )
    assert [s["count"] for s in only2] == [1]


async def test_history_series_rejects_unknown_interval(db_session):
    with pytest.raises(ValueError):
        await history_series(
            db_session, "GL-01", "汽压",
            from_=T0, to=T0 + timedelta(hours=1), interval="week",
        )


async def test_latest_values_status_coloring(db_session):
    """状态色：最新单点越界按规则 level 着色（与报警去抖口径分离）。"""
    await upsert_snapshots(
        db_session,
        [
            _reading("GL-01", "汽压", 0.8, T0),
            _reading("GL-01", "汽压", 1.2, T0 + timedelta(minutes=5)),   # 超上限
            _reading("GL-01", "水位", -60, T0 + timedelta(minutes=5), unit="mm"),  # 低于下限
        ],
        parse_method="template", raw_message_id="om_1", raw_excerpt="x",
    )
    from app.modules.safety.telemetry.rules import DEFAULT_RULES

    items = await latest_values(db_session, rules=DEFAULT_RULES)
    by_metric = {i["metric"]: i["status"] for i in items}
    assert by_metric["汽压"] == "warning"   # 默认汽压规则 level=warning
    assert by_metric["水位"] == "warning"
