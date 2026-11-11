"""周期聚合（周报/月报）纯函数单测——ticket 01 RED。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.safety.service.central_alarm.aggregator import (
    aggregate_period,
    get_natural_month_range,
    prev_natural_month_range,
    prev_natural_week_range,
)
from app.modules.safety.service.central_alarm.reader import CentralAlarmView

_BJ = timedelta(hours=8)


def _v(
    vid: str, bj: datetime, *, workshop: str = "车间一", post: str = "DCS 内操",
    alarm_type: str | None = None, pattern: str | None = None,
    analyzed: bool = False,
) -> CentralAlarmView:
    v = CentralAlarmView(
        id=vid,
        alarm_date=bj - _BJ,
        workshop=workshop,
        post=post,
        alarm_description="V0407 储罐 高高压报警",
    )
    v.ai_alarm_type = alarm_type
    v.ai_pattern = pattern
    if analyzed:
        v.ai_analyzed_at = datetime.now(UTC)
    return v


# ── 核心指标 ──


def test_aggregate_period_core_metrics() -> None:
    week_start, week_end = date(2026, 11, 2), date(2026, 11, 8)
    records = [
        _v("r1", datetime(2026, 11, 2, 10), pattern="false_alarm", analyzed=True),
        _v("r2", datetime(2026, 11, 2, 22), pattern="false_alarm", analyzed=True),
        _v("r3", datetime(2026, 11, 4, 8), pattern="repeated", analyzed=True),
        _v("r4", datetime(2026, 11, 8, 23), pattern=None, analyzed=False),
    ]
    agg = aggregate_period(
        records, kind="weekly", period_start=week_start, period_end=week_end,
    )
    assert agg.total == 4
    assert agg.days == 7
    assert agg.daily_avg == round(4 / 7, 1)
    # daily_counts 按北京时间日聚合（r2 的 BJ 22:00 与 r1 同日）
    assert agg.daily_counts == {
        date(2026, 11, 2): 2, date(2026, 11, 4): 1, date(2026, 11, 8): 1,
    }
    assert agg.analyzed_count == 3
    assert agg.false_alarm_count == 2
    assert agg.false_alarm_ratio == round(2 / 3, 4)


def test_false_alarm_ratio_none_when_unanalyzed() -> None:
    records = [_v("r1", datetime(2026, 11, 3, 10))]  # 未分析
    agg = aggregate_period(
        records, kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
    )
    assert agg.analyzed_count == 0
    assert agg.false_alarm_ratio is None


def test_top_hotspots_top10_desc() -> None:
    records: list[CentralAlarmView] = []
    # 12 个不同报警点：编号越大次数越多 → 只有前 10 入榜且按次数降序
    for i in range(1, 13):
        for _ in range(i):
            records.append(
                _v(f"r{i}-{_}", datetime(2026, 11, 3, 10),
                   workshop=f"车间{i}", post=f"岗位{i}", alarm_type="高高压")
            )
    agg = aggregate_period(
        records, kind="monthly",
        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
    )
    assert len(agg.top_hotspots) == 10
    counts = [c for *_spot, c in agg.top_hotspots]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 12 and counts[-1] == 3
    # 次数最少的两个点位（1 次/2 次）落榜
    spots = {(ws, post) for ws, post, _t, _c in agg.top_hotspots}
    assert ("车间1", "岗位1") not in spots
    assert ("车间12", "岗位12") in spots


def test_hotspot_grouping_ignores_none_as_question() -> None:
    records = [_v("r1", datetime(2026, 11, 3, 10), alarm_type=None)]
    records[0].workshop = None
    records[0].post = None
    agg = aggregate_period(
        records, kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
    )
    assert agg.top_hotspots[0][:3] == ("?", "?", "其他")


# ── 环比（上一周期）──


def test_prev_stats_attached() -> None:
    prev = [
        _v("p1", datetime(2026, 10, 26, 10), pattern="false_alarm", analyzed=True),
        _v("p2", datetime(2026, 10, 27, 10), pattern="repeated", analyzed=True),
        _v("p3", datetime(2026, 10, 28, 10), analyzed=False),
    ]
    agg = aggregate_period(
        [], kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
        prev_records=prev, prev_days=7,
    )
    assert agg.prev is not None
    assert agg.prev.total == 3
    assert agg.prev.days == 7
    assert agg.prev.daily_avg == round(3 / 7, 1)
    assert agg.prev.false_alarm_ratio == 0.5  # 1 误报 / 2 已分析


def test_prev_none_when_not_provided() -> None:
    agg = aggregate_period(
        [], kind="weekly",
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
    )
    assert agg.prev is None


# ── 窗口推导 ──


def test_prev_natural_week_range() -> None:
    # 周一触发 → 上一完整自然周
    assert prev_natural_week_range(date(2026, 11, 9)) == (
        date(2026, 11, 2), date(2026, 11, 8),
    )
    # 周中触发 → 仍是 ref 所在周的上一完整周
    assert prev_natural_week_range(date(2026, 11, 11)) == (
        date(2026, 11, 2), date(2026, 11, 8),
    )


def test_natural_month_range_and_cross_year_prev() -> None:
    assert get_natural_month_range(date(2026, 11, 15)) == (
        date(2026, 11, 1), date(2026, 11, 30),
    )
    # 闰年 2 月
    assert get_natural_month_range(date(2028, 2, 10)) == (
        date(2028, 2, 1), date(2028, 2, 29),
    )
    # 跨年：1 月触发 → 上一年 12 月
    assert prev_natural_month_range(date(2026, 1, 15)) == (
        date(2025, 12, 1), date(2025, 12, 31),
    )
    assert prev_natural_month_range(date(2026, 11, 10)) == (
        date(2026, 10, 1), date(2026, 10, 31),
    )
