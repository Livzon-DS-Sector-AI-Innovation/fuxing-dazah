"""历史定格聚合测试（S1 二期）。

接缝：build_standard_history 直插 snapshot 行读回（db_session 回滚隔离，
2099 年自隔离）；period 排序/标签纯函数直测。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.safety.models.standard_check import StandardCheckSnapshot
from app.modules.safety.service.standard_check import history as sc_history


@pytest.fixture(autouse=True)
async def _ensure_snapshot_table(db_session):
    """测试事务内确保表存在（与 test_standard_check_freeze 同手法）。"""

    def _create(ctx) -> None:
        StandardCheckSnapshot.__table__.create(ctx.connection(), checkfirst=True)

    await db_session.run_sync(_create)
    yield


def _snap(
    no: str, period_key: str, status: str, *, year: int = 2099,
    clause: str = "条款文本", department: list[str] | None = None,
    operator: str = "≥", target: float = 1, unit: str = "次",
    actual_display: str | None = "1次",
) -> StandardCheckSnapshot:
    return StandardCheckSnapshot(
        standard_no=no, year=year, period_key=period_key, status=status,
        metric_key="drill.count.evacuation" if status != "manual_done" else None,
        operator=operator, target_value=target, unit=unit,
        actual_display=actual_display,
        evidence={"window": {"start": "2099-01-01", "end": "2099-12-31"}},
        frozen_at=datetime(2099, 10, 1, 0, 20, tzinfo=UTC),
        clause=clause, element="应急管理", period="年度",
        department=department or ["安环部"],
    )


class TestPeriodHelpers:
    def test_sort_key_order(self) -> None:
        keys = ["2099-09", "2099", "2099H2", "2099-Q3", "2099H1", "2099-Q1", "2099-01"]
        assert sorted(keys, key=sc_history.period_sort_key) == [
            "2099", "2099H2", "2099H1", "2099-Q3", "2099-Q1", "2099-09", "2099-01",
        ]

    def test_labels(self) -> None:
        assert sc_history.period_label("2099") == "2099 年度"
        assert sc_history.period_label("2099H2") == "2099 下半年"
        assert sc_history.period_label("2099-Q3") == "2099 第三季度"
        assert sc_history.period_label("2099-09") == "2099 年 9 月"


class TestBuildHistory:
    async def test_live_grouping_and_summary(self, db_session) -> None:
        db_session.add_all([
            _snap("D6-03", "2099", "in_progress"),
            _snap("D6-03", "2099-Q3", "achieved"),
            _snap("D1-03", "2099-Q3", "manual_done"),
            _snap("D5-04", "2099-Q3", "missed"),
            _snap("D3-06", "2099-07", "no_data"),
            _snap("D0-01", "2098", "achieved", year=2098),  # 他年行不混入
        ])
        await db_session.flush()
        data = await sc_history.build_standard_history(2099, db=db_session)
        assert data["status"] == "live"
        assert data["year"] == 2099
        assert data["available_years"] == [2099, 2098]
        assert [p["period_key"] for p in data["periods"]] == [
            "2099", "2099-Q3", "2099-07",
        ]
        annual = data["periods"][0]
        assert annual["label"] == "2099 年度"
        assert annual["summary"]["in_progress"] == 1
        q3 = data["periods"][1]
        assert q3["summary"]["achieved"] == 1
        assert q3["summary"]["manual_done"] == 1
        assert q3["summary"]["missed"] == 1
        assert q3["summary"]["compliance_rate"] == 67  # 2/(2+1)
        row = q3["rows"][0]
        assert row["target_display"] == "≥1次"
        assert row["department"] == ["安环部"]

    async def test_empty_year(self, db_session) -> None:
        db_session.add(_snap("D0-01", "2098", "achieved", year=2098))
        await db_session.flush()
        data = await sc_history.build_standard_history(2099, db=db_session)
        assert data["status"] == "empty"
        assert data["periods"] == []
        assert data["available_years"] == [2098]  # 引导切到有快照的年份
