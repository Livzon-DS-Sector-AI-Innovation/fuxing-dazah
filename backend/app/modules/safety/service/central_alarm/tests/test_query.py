"""Ticket 05：query 直读与 stats 直读单测（注入替身 reader）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.safety.service.central_alarm import query as ca_query
from app.modules.safety.service.central_alarm.reader import CentralAlarmView

_BJ = timedelta(hours=8)


class FakeReader:
    def __init__(self, views: list[CentralAlarmView], total_count: int = 0) -> None:
        self._views = views
        self._total = total_count
        self.calls: list[str] = []

    async def fetch_window_records(
        self, *, start_utc: datetime, end_utc: datetime, strict: bool = False,
    ) -> list[CentralAlarmView]:
        self.calls.append(f"{start_utc.isoformat()}~{end_utc.isoformat()}")
        return [
            v for v in self._views
            if v.alarm_date and start_utc <= v.alarm_date < end_utc
        ]

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        from app.modules.safety.service.central_alarm import reader as ca_reader

        start, end = ca_reader.day_window(target_date)
        return await self.fetch_window_records(start_utc=start, end_utc=end)

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[CentralAlarmView], datetime, datetime]:
        from app.modules.safety.service.central_alarm import reader as ca_reader

        start, end = ca_reader.rolling_window(target_date)
        views = await self.fetch_window_records(start_utc=start, end_utc=end)
        return views, start, end

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        from app.modules.safety.service.central_alarm import reader as ca_reader

        start, end = ca_reader.week_window(week_start, week_end)
        return await self.fetch_window_records(start_utc=start, end_utc=end)

    async def count_total(self) -> int:
        self.calls.append("count_total")
        return self._total


def _view(
    record_id: str,
    *,
    bj_dt: datetime,
    workshop: str = "车间一",
    post: str = "DCS 内操",
    desc: str = "高高压力报警",
    note: str | None = None,
) -> CentralAlarmView:
    return CentralAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        alarm_date=bj_dt - _BJ,
        workshop=workshop,
        line="达托",
        post=post,
        alarm_description=desc,
        special_note=note,
    )


_VIEWS = [
    _view("a", bj_dt=datetime(2026, 9, 20, 10, tzinfo=UTC)),
    _view("b", bj_dt=datetime(2026, 9, 19, 10, tzinfo=UTC), workshop="车间二"),
    _view("c", bj_dt=datetime(2026, 9, 18, 10, tzinfo=UTC), desc="普通液位波动"),
    _view("d", bj_dt=datetime(2026, 9, 10, 10, tzinfo=UTC)),  # 7 天窗口外
]


async def test_default_window_is_last_7_days() -> None:
    r = FakeReader(_VIEWS)
    result = await ca_query.query_central_alarms_direct(reader=r)
    # 默认窗口覆盖 9/18~9/20 的记录（9/10 窗口外）
    assert result.total == 3
    assert len(r.calls) == 1


async def test_explicit_window_overrides_default() -> None:
    r = FakeReader(_VIEWS)
    result = await ca_query.query_central_alarms_direct(
        reader=r, date_from=date(2026, 9, 9), date_to=date(2026, 9, 11),
    )
    assert result.total == 1
    assert result.items[0].id == "d"


async def test_filters_and_pagination_desc() -> None:
    r = FakeReader(_VIEWS)
    result = await ca_query.query_central_alarms_direct(
        reader=r, workshop="车间一", page=1, page_size=1,
    )
    assert result.total == 2  # a + c（同车间）
    assert [v.id for v in result.items] == ["a"]  # 倒序第一页

    result2 = await ca_query.query_central_alarms_direct(
        reader=r, workshop="车间一", page=2, page_size=1,
    )
    assert [v.id for v in result2.items] == ["c"]


async def test_keyword_filter_matches_description_and_note() -> None:
    r = FakeReader([
        _view("k1", bj_dt=datetime(2026, 9, 20, 10, tzinfo=UTC), desc="储罐高高液位"),
        _view("k2", bj_dt=datetime(2026, 9, 20, 9, tzinfo=UTC), desc="温度正常",
              note="泡碱操作"),
        _view("k3", bj_dt=datetime(2026, 9, 20, 8, tzinfo=UTC), desc="无关"),
    ])
    result = await ca_query.query_central_alarms_direct(reader=r, keyword="高高")
    assert result.total == 1
    result2 = await ca_query.query_central_alarms_direct(reader=r, keyword="泡碱")
    assert result2.total == 1
    assert result2.items[0].id == "k2"


async def test_ai_filters_silently_ignored() -> None:
    r = FakeReader(_VIEWS)
    # ai_* 参数传入被忽略（不报错、不影响结果集）
    result = await ca_query.query_central_alarms_direct(
        reader=r, ai_alarm_type="高液位", ai_pattern="repeated",
        ai_dimension="equipment",
    )
    assert result.total == 3


def test_serialize_view_ai_fields_null() -> None:
    v = _view("s1", bj_dt=datetime(2026, 9, 20, 10, tzinfo=UTC))
    d = ca_query.serialize_view(v)
    assert d["id"] == "s1"
    assert d["ai_alarm_type"] is None
    assert d["ai_reason_analysis"] is None
    assert d["workshop"] == "车间一"
    assert d["created_at"] is None


async def test_stats_direct_shape() -> None:
    r = FakeReader(
        [
            _view("a", bj_dt=datetime(2026, 9, 20, 10, tzinfo=UTC)),
            _view("b", bj_dt=datetime(2026, 9, 19, 10, tzinfo=UTC),
                  workshop="车间二", post="外操"),
        ],
        total_count=29112,
    )
    stats = await ca_query.get_stats_direct(date(2026, 9, 20), reader=r)
    assert stats["today_total"] == 1
    assert stats["total_count"] == 29112
    assert stats["workshop_distribution"] == {"车间一": 1, "车间二": 1}
    assert stats["post_distribution"] == {"DCS 内操": 1, "外操": 1}
    assert stats["week_ai_analyzed_count"] == 0  # 直读 AI 不落盘 → 恒 0
    assert "count_total" in r.calls
